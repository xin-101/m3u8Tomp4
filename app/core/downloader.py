"""分片下载器: 并发下载、AES-128 解密、断点状态管理.

TaskWorker 负责单个任务的完整生命周期:
解析 → 下载分片(线程池) → 状态持久化 → FFmpeg 合并/转换。
"""

import json
import logging
import os
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QTimer, QThread, Signal
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from app.core.ffmpeg_engine import FFmpegEngine
from app.core.m3u8_parser import DRMProtectedError, M3U8Info, ParseError, parse_m3u8
from app.core.speed_controller import SpeedController

logger = logging.getLogger("m3u8ToMp4.downloader")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SEGMENT_TIMEOUT = 30


class DownloadError(Exception):
    """下载失败."""


class _Aborted(Exception):
    """内部: 暂停/取消导致的中断(不计为失败)."""


def _make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32, max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def _try_decrypt_aes128(data: bytes, key: bytes, iv: bytes | None, sequence: int) -> bytes:
    """AES-128-CBC 解密. 无 iv 时按 HLS 规范用 16 字节大端序 sequence."""
    from Crypto.Cipher import AES

    if iv is None:
        iv = sequence.to_bytes(16, "big")
    if len(iv) < 16:
        iv = iv.rjust(16, b"\x00")
    cipher = AES.new(key, AES.MODE_CBC, iv[:16])
    plain = cipher.decrypt(data)
    # 去除 PKCS7 填充
    if plain:
        pad = plain[-1]
        if 1 <= pad <= 16 and len(plain) >= pad and plain[-pad:] == bytes([pad]) * pad:
            plain = plain[:-pad]
    return plain


@dataclass
class SegmentRecord:
    """state.json 中的分片记录."""

    index: int
    uri: str
    duration: float = 0.0
    done: bool = False
    size: int = 0
    key_uri: str = ""
    key_iv: str = ""
    sequence: int = 0


@dataclass
class TaskState:
    """断点续传状态(持久化到 download_cache/<id>/state.json)."""

    task_id: str = ""
    url: str = ""
    name: str = ""
    status: str = "等待"
    total_segments: int = 0
    duration: float = 0.0
    resolution: str = ""
    segment_type: str = "ts"
    encrypted: bool = False
    key_method: str = ""
    key_url: str = ""
    referer: str = ""
    auto_convert: bool = True
    output_format: str = "mp4"
    threads: int = 5
    local_input: bool = False
    segments: list[SegmentRecord] = field(default_factory=list)
    updated_time: float = 0.0

    def done_count(self) -> int:
        return sum(1 for s in self.segments if s.done)

    def save(self, cache_dir: str):
        self.updated_time = time.time()
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, "state.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    @classmethod
    def load(cls, cache_dir: str) -> "TaskState | None":
        path = os.path.join(cache_dir, "state.json")
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            segs = [SegmentRecord(**s) for s in raw.pop("segments", [])]
            state = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            state.segments = segs
            return state
        except Exception as exc:
            logger.warning("状态文件损坏, 忽略: %s", exc)
            return None


class TaskWorker(QObject):
    """单任务工作线程(在 QThread 中执行)."""

    status_changed = Signal(str, str)          # task_id, status
    progress_changed = Signal(str, float, float, float, float)  # task_id, percent, speed, downloaded, eta
    log_emitted = Signal(str, str)             # task_id, message
    completed = Signal(str, str)               # task_id, output_path
    failed = Signal(str, str)                  # task_id, reason

    def __init__(self, task_id: str, name: str, url: str, download_dir: str,
                 cache_root: str, speed: SpeedController, config=None, parent=None):
        super().__init__(parent)
        self.task_id = task_id
        self.name = name
        self.url = url
        self.download_dir = download_dir
        self.cache_root = cache_root
        self.speed = speed
        self.config = config
        self.threads = 5
        self.referer = ""
        self.auto_convert = True
        self.output_format = "mp4"
        self.force_reencode = False

        self._pause = threading.Event()      # set = 暂停中
        self._cancel = threading.Event()
        self._error_abort = False            # 分片失败过多
        self._state: TaskState | None = None
        self._session = _make_session()
        self._lock = threading.Lock()
        self._downloaded = 0.0
        self._total_size = -1.0
        self._start_time = 0.0
        self._last_tick = 0.0
        self._last_bytes = 0.0
        self._last_speed = 0.0
        self._ffmpeg: FFmpegEngine | None = None
        self._progress_stop: threading.Event | None = None
        self._progress_thread: threading.Thread | None = None
        self._thread: QThread | None = None

    # ---------- 控制 ----------
    def request_pause(self):
        """暂停: 中断当前运行(状态已按分片粒度存盘), 恢复时重新 launch 续传."""
        self._pause.set()
        logger.info("任务 %s 请求暂停", self.task_id)

    def request_resume(self):
        self._pause.clear()

    def request_cancel(self):
        self._cancel.set()
        if self._ffmpeg:
            self._ffmpeg.cancel()

    @property
    def _aborted(self) -> bool:
        return self._pause.is_set() or self._cancel.is_set()

    @property
    def cache_dir(self) -> str:
        return os.path.join(self.cache_root, self.task_id)

    # ---------- 主流程 ----------
    def run(self):
        """在线程内执行(由 QThread 调用)."""
        try:
            self._run_inner()
        except DRMProtectedError as exc:
            self._fail(str(exc))
        except (ParseError, DownloadError) as exc:
            self._fail(str(exc))
        except Exception as exc:
            logger.exception("任务 %s 异常", self.task_id)
            self._fail(f"未知错误: {exc}")

    def _run_inner(self):
        self._start_time = time.monotonic()
        self._last_tick = self._start_time
        os.makedirs(self.download_dir, exist_ok=True)

        self._set_status("解析中")
        state = TaskState.load(self.cache_dir)
        is_local = os.path.isfile(self.url)

        if state and state.segments and state.url == self.url:
            self._state = state
            self._log(f"发现断点状态: {state.done_count()}/{state.total_segments} 分片已完成, 续传中")
            logger.info("任务 %s 续传: %s/%s", self.task_id, state.done_count(), state.total_segments)
        else:
            if state:
                shutil.rmtree(self.cache_dir, ignore_errors=True)
            info = parse_m3u8(self.url, self.name)
            self._state = self._state_from_info(info)
            if not self.name or self.name == "未命名视频":
                self.name = info.title
                self._state.name = self.name
            if self.referer and not self._state.referer:
                self._state.referer = self.referer
            self._state.save(self.cache_dir)

        st = self._state
        st.local_input = is_local
        st.threads = self.threads
        st.auto_convert = self.auto_convert
        st.output_format = self.output_format

        if is_local:
            # 本地 m3u8: 无需下载, 直接转换
            self._log("检测到本地 m3u8, 跳过下载直接转换")
            self._total_size = 0
            self._set_status("转换中" if st.auto_convert else "合并中")
            self._do_convert(self.url, local_source=True)
            return

        self._set_status("下载中")
        self._persist()
        self._start_progress_timer()
        try:
            self._download_segments()
        finally:
            self._stop_progress_timer()

        if self._pause.is_set():
            self._set_status("暂停")
            self._persist()
            self._log("任务已暂停, 进度已保存, 可随时恢复")
            return
        if self._cancel.is_set():
            self._set_status("暂停")
            self._persist()
            self._log("任务已取消, 进度已保存")
            return

        self._set_status("合并中")
        self._persist()
        playlist = self._write_local_playlist()
        self._set_status("转换中" if st.auto_convert else "合并中")
        self._do_convert(playlist)

    def _state_from_info(self, info: M3U8Info) -> TaskState:
        segs = [
            SegmentRecord(
                index=i,
                uri=s.uri,
                duration=s.duration,
                done=False,
                key_uri=s.key_uri,
                key_iv=s.key_iv,
                sequence=s.sequence,
            )
            for i, s in enumerate(info.segments)
        ]
        return TaskState(
            task_id=self.task_id,
            url=self.url,
            name=self.name,
            total_segments=len(segs),
            duration=info.duration,
            resolution=info.resolution,
            segment_type=info.segment_type,
            encrypted=info.encrypted,
            key_method=info.key_method,
            key_url=info.key_url,
            referer=self.referer,
            segments=segs,
        )

    # ---------- 下载 ----------
    def _download_segments(self):
        st = self._state
        pending = [s for s in st.segments if not s.done]
        if not pending:
            self._log("所有分片已下载完成")
            return
        self._log(f"开始下载 {len(pending)} 个分片 (共 {st.total_segments}), 线程数 {self.threads}")
        key_cache: dict[str, bytes] = {}
        if st.encrypted and st.key_method == "AES-128" and st.key_url:
            key_cache[st.key_url] = self._fetch_key(st.key_url)

        errors: list[str] = []
        with ThreadPoolExecutor(max_workers=max(1, self.threads)) as pool:
            futures = {pool.submit(self._download_one, seg, key_cache): seg for seg in pending}
            for future in as_completed(futures):
                if self._aborted:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                seg = futures[future]
                try:
                    future.result()
                except _Aborted:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                except Exception as exc:
                    errors.append(f"分片{seg.index}: {exc}")
                    logger.warning("任务 %s 分片 %s 失败: %s", self.task_id, seg.index, exc)
                    if len(errors) >= 5:
                        self._error_abort = True
                        pool.shutdown(wait=False, cancel_futures=True)
                        break

        if self._error_abort:
            raise DownloadError(f"多个分片下载失败: {errors[0]} 等 {len(errors)} 个")
        if errors:
            # 少量失败: 重试一轮
            retry = [s for s in st.segments if not s.done]
            if retry:
                self._log(f"重试 {len(retry)} 个失败分片 ...")
                still_failed = 0
                for seg in retry:
                    if self._aborted:
                        break
                    try:
                        self._download_one(seg, key_cache)
                    except _Aborted:
                        break
                    except Exception as exc:
                        still_failed += 1
                        logger.warning("重试仍失败 分片%s: %s", seg.index, exc)
                if still_failed and not self._aborted:
                    raise DownloadError(f"{still_failed} 个分片下载失败")

    def _download_one(self, seg: SegmentRecord, key_cache: dict[str, bytes]):
        if self._aborted:
            raise _Aborted()
        if seg.done:
            return

        seg_path = self._segment_path(seg)
        if os.path.isfile(seg_path) and os.path.getsize(seg_path) > 0:
            seg.done = True
            seg.size = os.path.getsize(seg_path)
            return

        headers = {}
        if self._state and self._state.referer:
            headers["Referer"] = self._state.referer
        try:
            resp = self._session.get(seg.uri, stream=True, timeout=SEGMENT_TIMEOUT, headers=headers)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise DownloadError(f"请求失败: {exc}") from exc

        chunks: list[bytes] = []
        try:
            for chunk in resp.iter_content(64 * 1024):
                if self._aborted:
                    resp.close()
                    raise _Aborted()
                if not chunk:
                    continue
                self.speed.acquire(len(chunk))
                self.speed.record(len(chunk))
                with self._lock:
                    self._downloaded += len(chunk)
                chunks.append(chunk)
        finally:
            resp.close()

        data = b"".join(chunks)
        if not data:
            raise DownloadError("空响应")

        if self._state and self._state.encrypted and self._state.key_method == "AES-128":
            key_uri = seg.key_uri or self._state.key_url
            if key_uri:
                if key_uri not in key_cache:
                    key_cache[key_uri] = self._fetch_key(key_uri)
                key = key_cache[key_uri]
                if key:
                    iv = _parse_iv(seg.key_iv)
                    data = _try_decrypt_aes128(data, key, iv, seg.sequence)

        tmp = seg_path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, seg_path)
        seg.done = True
        seg.size = len(data)
        with self._lock:
            self._total_size = max(self._total_size, 0)
        self._maybe_persist(seg)

    def _maybe_persist(self, seg: SegmentRecord):
        """每 20 个分片保存一次状态(降低 IO)."""
        if seg.index % 20 == 0 and self._state:
            self._state.save(self.cache_dir)

    def _fetch_key(self, key_uri: str) -> bytes | None:
        local = key_uri
        if os.path.isfile(local):
            with open(local, "rb") as fh:
                return fh.read()
        headers = {}
        if self._state and self._state.referer:
            headers["Referer"] = self._state.referer
        try:
            resp = self._session.get(key_uri, timeout=SEGMENT_TIMEOUT, headers=headers)
            resp.raise_for_status()
            key = resp.content
            if len(key) not in (16, 24, 32):
                self._log(f"警告: 密钥长度异常 ({len(key)} bytes)")
            self._log(f"已获取 AES 密钥 ({len(key)} bytes)")
            # 缓存到本地
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                with open(os.path.join(self.cache_dir, "key.bin"), "wb") as fh:
                    fh.write(key)
            except OSError:
                pass
            return key
        except Exception as exc:
            raise DownloadError(f"获取解密密钥失败: {exc}") from exc

    def _segment_path(self, seg: SegmentRecord) -> str:
        ext = ".m4s" if self._state and self._state.segment_type == "fmp4" else ".ts"
        return os.path.join(self.cache_dir, f"seg_{seg.index:06d}{ext}")

    # ---------- 合并/转换 ----------
    def _write_local_playlist(self) -> str:
        st = self._state
        files = []
        durations = []
        for seg in st.segments:
            path = self._segment_path(seg)
            if not os.path.isfile(path):
                raise DownloadError(f"分片缺失: {seg.index}")
            files.append(path)
            durations.append(seg.duration)
        playlist_path = os.path.join(self.cache_dir, "local.m3u8")
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:VOD",
                 f"#EXT-X-TARGETDURATION:{int(max(durations or [10])) + 1}",
                 "#EXT-X-MEDIA-SEQUENCE:0"]
        for path, dur in zip(files, durations):
            lines.append(f"#EXTINF:{dur:.3f},")
            lines.append(os.path.abspath(path).replace("\\", "/"))
        lines.append("#EXT-X-ENDLIST")
        with open(playlist_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return playlist_path

    def _do_convert(self, input_path: str, local_source: bool = False):
        st = self._state
        out_ext = (st.output_format if st else self.output_format) or "mp4"
        safe_name = self.name or "output"
        output_path = self._unique_output_path(safe_name, out_ext)

        if local_source and st and not st.auto_convert:
            self._finish(os.path.abspath(input_path))
            return

        total = st.duration if st else 0.0
        ffmpeg = FFmpegEngine(self.config.ffmpeg_path if self.config else "")
        self._ffmpeg = ffmpeg
        ffmpeg.log_line.connect(lambda line: self._log(f"[ffmpeg] {line}"))
        ffmpeg.progress.connect(lambda pct: self._emit_progress(pct))
        extra = []
        if st and st.referer and not local_source:
            extra = ["-headers", f"Referer: {st.referer}\r\n"]
        ok, result = ffmpeg.convert_blocking(
            input_path, output_path, total, out_ext,
            extra_input_args=extra, fallback_reencode=True,
        )
        self._ffmpeg = None
        if ok:
            self._finish(result)
        elif result == "已取消":
            self._persist()
            self._set_status("暂停")
            self._log("任务已暂停")
        else:
            self._fail(result)

    def _unique_output_path(self, name: str, ext: str) -> str:
        from app.ui.task_widget import sanitize_filename
        base = sanitize_filename(name)
        candidate = os.path.join(self.download_dir, f"{base}.{ext}")
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(self.download_dir, f"{base}({counter}).{ext}")
            counter += 1
        return candidate

    # ---------- 状态上报 ----------
    def _set_status(self, status: str):
        if self._state:
            self._state.status = status
        self.status_changed.emit(self.task_id, status)

    def _log(self, message: str):
        logger.info("[任务%s] %s", self.task_id, message)
        self.log_emitted.emit(self.task_id, message)

    def _persist(self):
        if self._state:
            self._state.save(self.cache_dir)

    def _start_progress_timer(self):
        """启动进度上报(纯线程实现, 不依赖 Qt 事件循环)."""
        self._progress_stop = threading.Event()

        def loop():
            while not self._progress_stop.wait(0.5):
                try:
                    self._tick_progress()
                except Exception:
                    logger.debug("进度上报异常", exc_info=True)

        self._progress_thread = threading.Thread(target=loop, daemon=True, name=f"prog-{self.task_id}")
        self._progress_thread.start()

    def _stop_progress_timer(self):
        if getattr(self, "_progress_stop", None):
            self._progress_stop.set()
        self._progress_thread = None

    def _tick_progress(self):
        self._emit_progress()

    def _emit_progress(self, override_pct: float | None = None):
        st = self._state
        if not st:
            return
        now = time.monotonic()
        with self._lock:
            downloaded = self._downloaded
        # 速度(EMA 平滑)
        elapsed = max(now - self._last_tick, 0.001)
        speed = (downloaded - self._last_bytes) / elapsed
        self._last_speed = self._last_speed * 0.6 + speed * 0.4
        self._last_tick = now
        self._last_bytes = downloaded

        if override_pct is not None:
            pct = override_pct
        elif st.total_segments:
            done_bytes = sum(s.size for s in st.segments if s.done)
            pct = st.done_count() / st.total_segments * 100.0
        else:
            pct = 0.0
            done_bytes = 0.0
        eta = -1.0
        if override_pct is None and self._last_speed > 0 and pct < 100 and st.total_segments:
            done_bytes = sum(s.size for s in st.segments if s.done)
            avg = done_bytes / max(st.done_count(), 1)
            remain_bytes = (st.total_segments - st.done_count()) * avg
            eta = remain_bytes / self._last_speed
        self.progress_changed.emit(self.task_id, pct, self._last_speed, downloaded, eta)

    def _finish(self, output_path: str):
        self._set_status("完成")
        # 清理缓存
        try:
            shutil.rmtree(self.cache_dir, ignore_errors=True)
        except Exception:
            pass
        self.completed.emit(self.task_id, os.path.abspath(output_path))

    def _fail(self, reason: str):
        self._set_status("失败")
        self._persist()
        self.failed.emit(self.task_id, reason)


def _parse_iv(iv_text: str) -> bytes | None:
    if not iv_text:
        return None
    text = iv_text.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    try:
        return bytes.fromhex(text)
    except ValueError:
        return None
