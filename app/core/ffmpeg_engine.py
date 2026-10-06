"""FFmpeg 集成模块.

- 自动定位 ffmpeg: resources/ffmpeg.exe → 程序目录 → 系统 PATH
- 快速封装(-c copy), 失败自动回退 libx264/aac 重编码
- 通过 Qt 信号实时上报进度与日志
"""

import logging
import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

logger = logging.getLogger("m3u8ToMp4.ffmpeg")


def _resource_dirs() -> list[Path]:
    """候选资源目录(兼容 PyInstaller 打包)."""
    dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        dirs.append(Path(sys.executable).parent)
        dirs.append(base)
        dirs.append(base / "resources")
    dirs.append(Path(__file__).resolve().parent.parent.parent / "resources")
    dirs.append(Path.cwd() / "resources")
    return dirs


def locate_ffmpeg(configured: str = "") -> str | None:
    """按优先级查找 ffmpeg 可执行文件, 找不到返回 None."""
    if configured and configured.lower() not in ("", "ffmpeg"):
        if os.path.isfile(configured):
            return configured
        if os.path.isfile(configured + ".exe"):
            return configured + ".exe"
    names = ["ffmpeg.exe", "ffmpeg"] if os.name == "nt" else ["ffmpeg"]
    for directory in _resource_dirs():
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def ffmpeg_version(ffmpeg_path: str) -> str:
    """返回 ffmpeg 版本字符串, 失败返回空."""
    try:
        proc = QProcess()
        proc.start(ffmpeg_path, ["-version"])
        if not proc.waitForFinished(5000):
            return ""
        out = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
        match = re.search(r"ffmpeg version (\S+)", out)
        return match.group(1) if match else ""
    except Exception as exc:
        logger.debug("获取ffmpeg版本失败: %s", exc)
        return ""


class FFmpegEngine(QObject):
    """ffmpeg 转换引擎(QProcess 异步, 不阻塞 UI)."""

    progress = Signal(float)          # 0 ~ 100
    log_line = Signal(str)            # ffmpeg 输出行
    started = Signal(str)             # 输出路径
    finished_ok = Signal(str)         # 成功, 输出路径
    failed = Signal(str)              # 失败原因

    def __init__(self, ffmpeg_path: str = "", parent=None):
        super().__init__(parent)
        self.ffmpeg_path = self._resolve_path(ffmpeg_path)
        self._process: QProcess | None = None
        self._total_duration = 0.0
        self._current_args: list[str] = []
        self._attempt = 0
        self._input_path = ""
        self._output_path = ""
        self._output_format = "mp4"
        self._use_copy = True
        self._extra_input_args: list[str] = []
        self._cancelled = False
        self._fallback_enabled = True

    @staticmethod
    def _resolve_path(configured: str) -> str:
        """解析 ffmpeg 路径: 明确文件优先, 否则全盘查找."""
        if configured and os.path.isfile(configured):
            return configured
        found = locate_ffmpeg(configured)
        if found:
            return found
        if configured and shutil.which(configured):
            return configured
        return ""

    # ---------- 对外接口 ----------
    def is_running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.NotRunning

    def convert(
        self,
        input_path: str,
        output_path: str,
        total_duration: float = 0.0,
        output_format: str = "mp4",
        extra_input_args: list[str] | None = None,
        fallback_reencode: bool = True,
    ) -> bool:
        """启动转换. 返回是否成功发起."""
        if self.is_running():
            self.failed.emit("已有转换任务在运行")
            return False
        if not self.ffmpeg_path:
            self.ffmpeg_path = locate_ffmpeg() or ""
        if not self.ffmpeg_path:
            self.failed.emit("未找到 FFmpeg, 请在设置中指定 ffmpeg.exe 路径(可放入 resources/ 目录)")
            return False
        if not os.path.exists(input_path):
            self.failed.emit(f"输入文件不存在: {input_path}")
            return False

        self._input_path = input_path
        self._output_path = output_path
        self._total_duration = max(float(total_duration), 0.0)
        self._output_format = output_format.lstrip(".").lower() or "mp4"
        self._extra_input_args = list(extra_input_args or [])
        self._fallback_enabled = fallback_reencode
        self._use_copy = True
        self._attempt = 1
        self._cancelled = False
        return self._launch()

    def cancel(self):
        self._cancelled = True
        if self._process and self._process.state() != QProcess.NotRunning:
            self._process.kill()

    def convert_blocking(
        self,
        input_path: str,
        output_path: str,
        total_duration: float = 0.0,
        output_format: str = "mp4",
        extra_input_args: list[str] | None = None,
        fallback_reencode: bool = True,
    ) -> tuple[bool, str]:
        """同步转换(基于 QProcess 阻塞API, 无需 Qt 事件循环).

        返回 (success, output_path 或 错误信息). 自动尝试 -c copy,
        失败后回退 libx264/aac 重编码。
        """
        if not self.ffmpeg_path:
            self.ffmpeg_path = locate_ffmpeg() or ""
        if not self.ffmpeg_path:
            return False, "未找到 FFmpeg, 请在设置中指定 ffmpeg.exe 路径(可放入 resources/ 目录)"
        if not os.path.exists(input_path):
            return False, f"输入文件不存在: {input_path}"

        self._input_path = input_path
        self._output_path = output_path
        self._total_duration = max(float(total_duration), 0.0)
        self._output_format = output_format.lstrip(".").lower() or "mp4"
        self._extra_input_args = list(extra_input_args or [])
        self._fallback_enabled = fallback_reencode
        self._cancelled = False
        self.started.emit(output_path)

        copy_mode = True
        attempt = 1
        last_error = ""
        while True:
            if self._cancelled:
                return False, "已取消"
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            args = self._build_args(copy_mode)
            logger.info("FFmpeg 阻塞启动 (attempt=%s, copy=%s)", attempt, copy_mode)
            process = QProcess()
            process.setProgram(self.ffmpeg_path)
            process.setArguments(args)
            process.setProcessChannelMode(QProcess.MergedChannels)
            process.start()
            if not process.waitForStarted(8000):
                return False, f"无法启动 FFmpeg: {process.errorString()}"

            tail_lines: list[str] = []
            aborted = False
            while process.state() != QProcess.NotRunning:
                if process.waitForReadyRead(200):
                    data = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
                    for line in data.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        self._handle_line(line)
                        if len(tail_lines) >= 40:
                            tail_lines.pop(0)
                        tail_lines.append(line)
                else:
                    process.waitForFinished(100)
                if self._cancelled:
                    aborted = True
                    process.kill()
                    process.waitForFinished(3000)
                    break
            # 排空剩余输出
            data = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")
            for line in data.splitlines():
                line = line.strip()
                if line:
                    self._handle_line(line)
                    if len(tail_lines) >= 40:
                        tail_lines.pop(0)
                    tail_lines.append(line)
            exit_code = process.exitCode()
            process.deleteLater()

            if aborted:
                return False, "已取消"
            output_ok = os.path.exists(output_path) and os.path.getsize(output_path) > 0
            if exit_code == 0 and output_ok:
                self.progress.emit(100.0)
                logger.info("FFmpeg 转换完成: %s", output_path)
                self.finished_ok.emit(output_path)
                return True, output_path

            error_line = next((l for l in reversed(tail_lines) if l), "")
            last_error = error_line
            logger.warning("FFmpeg 失败 exit=%s copy=%s err=%s", exit_code, copy_mode, error_line[:200])

            if copy_mode and self._fallback_enabled and attempt == 1:
                attempt = 2
                copy_mode = False
                self.log_line.emit("[回退] -c copy 失败, 自动切换 libx264 + aac 重编码 ...")
                continue
            break

        reason = f"FFmpeg 转换失败(退出码 {exit_code})"
        if last_error:
            reason += f": {last_error}"
        self.failed.emit(reason)
        return False, reason

    def _build_args(self, copy_mode: bool) -> list[str]:
        args = ["-hide_banner", "-y", "-nostdin"]
        args += self._extra_input_args
        args += ["-i", self._input_path]
        if copy_mode:
            args += ["-c", "copy"]
            if self._output_format == "mp4":
                args += ["-movflags", "+faststart"]
                # TS 转 mp4 需要处理可能存在的时间戳问题, copy 模式加 ignore_err
                args += ["-fflags", "+genpts"]
        else:
            args += [
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p",
            ]
            if self._output_format == "mp4":
                args += ["-movflags", "+faststart"]
        args += ["-progress", "pipe:1", "-nostats", self._output_path]
        return args

    def _launch(self) -> bool:
        args = self._build_args(self._use_copy)
        self._current_args = args
        logger.info("FFmpeg 启动 (attempt=%s, copy=%s): %s", self._attempt, self._use_copy, self.ffmpeg_path)

        process = QProcess(self)
        env = QProcessEnvironment.systemEnvironment()
        process.setProcessEnvironment(env)
        process.setProgram(self.ffmpeg_path)
        process.setArguments(args)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._on_output)
        process.finished.connect(self._on_finished)
        self._process = process
        process.start()
        if not process.waitForStarted(8000):
            self.failed.emit(f"无法启动 FFmpeg: {process.errorString()}")
            self._process = None
            return False
        self.started.emit(self._output_path)
        return True

    # ---------- 内部回调 ----------
    def _on_output(self):
        if not self._process:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            self._handle_line(line)

    def _handle_line(self, line: str):
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                value = int(line.split("=", 1)[1])
                if self._total_duration > 0:
                    percent = min(value / 1_000_000 / self._total_duration * 100.0, 99.5)
                    self.progress.emit(percent)
            except (ValueError, IndexError):
                pass
        elif line.startswith("out_time="):
            try:
                parts = line.split("=", 1)[1].strip().split(":")
                if len(parts) == 3 and self._total_duration > 0:
                    h, m, s = (float(p) for p in parts)
                    seconds = h * 3600 + m * 60 + s
                    percent = min(seconds / self._total_duration * 100.0, 99.5)
                    self.progress.emit(percent)
            except (ValueError, IndexError):
                pass
        elif line.startswith("progress="):
            if "end" in line and self._total_duration <= 0:
                self.progress.emit(99.0)
        if self._is_log_line(line):
            self.log_line.emit(line)

    _LOG_PREFIXES = ("frame=", "size=", "time=", "bitrate=", "speed=", "Press [q]",
                     "ffmpeg version", "built with", "configuration:", "lib", "Input #",
                     "Output #", "Stream #", "Metadata:", "Duration:", "encoder")
    _LOG_KEYWORDS = ("error", "warning", "invalid", "failed", "deprecated",
                     "could not", "unable", "no such", "permission", "not found")

    def _is_log_line(self, line: str) -> bool:
        low = line.lower()
        if any(k in low for k in self._LOG_KEYWORDS):
            return True
        if line.startswith("frame=") or line.startswith("size="):
            return False
        return line.startswith(self._LOG_PREFIXES) or line.startswith("[")

    def _on_finished(self, exit_code: int, _status):
        process = self._process
        self._process = None
        if self._cancelled:
            self.failed.emit("已取消")
            return
        output_exists = os.path.exists(self._output_path) and os.path.getsize(self._output_path) > 0
        if exit_code == 0 and output_exists:
            self.progress.emit(100.0)
            logger.info("FFmpeg 转换完成: %s", self._output_path)
            self.finished_ok.emit(self._output_path)
            return

        tail = ""
        if process:
            tail = bytes(process.readAllStandardOutput()).decode("utf-8", "replace")[-800:]
        logger.warning("FFmpeg 退出码=%s, 尝试回退. tail=%s", exit_code, tail[-200:])

        if self._use_copy and self._fallback_enabled and self._attempt == 1:
            self._attempt = 2
            self._use_copy = False
            self.log_line.emit("[回退] -c copy 失败, 自动切换 libx264 + aac 重编码 ...")
            logger.info("回退到 libx264/aac 重编码")
            if os.path.exists(self._output_path):
                try:
                    os.remove(self._output_path)
                except OSError:
                    pass
            if self._launch():
                return
        reason = f"FFmpeg 转换失败(退出码 {exit_code})"
        if tail:
            reason += f": {tail.strip().splitlines()[-1] if tail.strip() else ''}"
        self.failed.emit(reason)

    # ---------- 静态便捷方法 ----------
    @staticmethod
    def build_local_playlist(segment_files: list[str], output_path: str,
                             durations: list[float] | None = None,
                             encrypted_keys: list[tuple[str, str, str]] | None = None) -> str:
        """为已下载分片生成本地 m3u8 播放列表(供 ffmpeg 合并)."""
        lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-PLAYLIST-TYPE:VOD"]
        target = max((d or 10.0 for d in (durations or [])), default=10.0)
        lines.append(f"#EXT-X-TARGETDURATION:{int(target) + 1}")
        lines.append("#EXT-X-MEDIA-SEQUENCE:0")
        for i, path in enumerate(segment_files):
            dur = durations[i] if durations and i < len(durations) and durations[i] else 10.0
            lines.append(f"#EXTINF:{dur:.3f},")
            lines.append(os.path.abspath(path).replace("\\", "/"))
        lines.append("#EXT-X-ENDLIST")
        content = "\n".join(lines)
        directory = os.path.dirname(os.path.abspath(output_path))
        os.makedirs(directory, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(content)
        return output_path
