"""M3U8(HLS) 解析模块.

支持本地文件与网络 URL, 解析 Master/Media Playlist,
输出统一数据模型 M3U8Info, 并对 DRM 加密做拦截。
"""

import logging
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import m3u8
import requests

logger = logging.getLogger("m3u8ToMp4.parser")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 15

DRM_METHODS = {"SAMPLE-AES", "SAMPLE-AES-CTR", "SAMPLE-AES-CENC"}
DRM_HINT_MARKERS = ("skd://", "com.widevine", "urn:uuid:edef8ba9")


class ParseError(Exception):
    """解析失败."""


class DRMProtectedError(ParseError):
    """视频使用 DRM 保护, 禁止处理."""


@dataclass
class VariantStream:
    """Master Playlist 中的一个变体流."""

    uri: str
    bandwidth: int = 0
    resolution: str = ""
    codecs: str = ""
    frame_rate: float = 0.0
    audio: str = ""

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0]) if "x" in self.resolution else 0

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1]) if "x" in self.resolution else 0


@dataclass
class MediaInfo:
    """音频轨信息."""

    type: str = ""
    uri: str = ""
    group_id: str = ""
    name: str = ""
    language: str = ""
    default: bool = False


@dataclass
class SegmentInfo:
    """单个分片."""

    uri: str = ""
    duration: float = 0.0
    byte_range: str = ""
    key_uri: str = ""
    key_method: str = ""
    key_iv: str = ""
    sequence: int = 0


@dataclass
class M3U8Info:
    """M3U8 解析结果."""

    url: str = ""
    title: str = ""
    duration: float = 0.0
    resolution: str = ""
    bandwidth: int = 0
    codecs: str = ""
    segments: list[SegmentInfo] = field(default_factory=list)
    variants: list[VariantStream] = field(default_factory=list)
    media: list[MediaInfo] = field(default_factory=list)
    encrypted: bool = False
    drm: bool = False
    key_method: str = ""
    key_url: str = ""
    is_master: bool = False
    segment_type: str = "ts"  # ts | fmp4
    version: int = 0
    target_duration: float = 0.0
    raw_content: str = ""
    base_uri: str = ""

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def resolution_label(self) -> str:
        return self.resolution or "未知"

    @property
    def bandwidth_label(self) -> str:
        if self.bandwidth <= 0:
            return "未知"
        if self.bandwidth >= 1_000_000:
            return f"{self.bandwidth / 1_000_000:.2f} Mbps"
        if self.bandwidth >= 1000:
            return f"{self.bandwidth / 1000:.0f} kbps"
        return f"{self.bandwidth} bps"

    @property
    def duration_label(self) -> str:
        total = int(self.duration)
        if total <= 0:
            return "未知"
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    @property
    def type_label(self) -> str:
        return "fMP4" if self.segment_type == "fmp4" else "TS"


def _is_url(path: str) -> bool:
    scheme = urlparse(path).scheme.lower()
    return scheme in ("http", "https")


def _fetch_text(url: str) -> str:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": f"{urlparse(url).scheme}://{urlparse(url).netloc}/"},
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except requests.RequestException as exc:
        raise ParseError(f"下载m3u8失败: {exc}") from exc


def _read_local(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        raise ParseError(f"读取本地m3u8失败: {exc}") from exc


def _base_uri(source: str) -> str:
    if _is_url(source):
        return source.rsplit("/", 1)[0] + "/" if "/" in source[8:] else source
    directory = os.path.dirname(os.path.abspath(source))
    return directory.replace("\\", "/") + "/"


def _resolve(uri: str, base: str) -> str:
    if not uri:
        return ""
    if _is_url(uri):
        return uri
    if _is_url(base):
        return urljoin(base, uri)
    if re.match(r"^[a-zA-Z]:[\\/]", uri) or uri.startswith("\\\\"):
        return uri.replace("\\", "/")
    return (base.rstrip("/") + "/" + uri).replace("//", "/") if "://" not in base else urljoin(base, uri)


def _norm_resolution(resolution) -> str:
    """归一化分辨率为 'WxH' 字符串."""
    if not resolution:
        return ""
    if isinstance(resolution, (tuple, list)) and len(resolution) == 2:
        return f"{resolution[0]}x{resolution[1]}"
    return str(resolution)


def _best_variant(variants: list[VariantStream]) -> VariantStream:
    """选择最佳变体: 优先分辨率, 其次带宽."""
    if not variants:
        raise ParseError("Master Playlist 中没有可用的变体流")
    return max(variants, key=lambda v: (v.height, v.bandwidth))


def _detect_segment_type(playlist) -> str:
    has_map = bool(playlist.segment_map)
    if has_map:
        return "fmp4"
    for seg in playlist.segments:
        uri = (seg.uri or "").lower()
        if uri.endswith(".m4s") or uri.endswith(".mp4"):
            return "fmp4"
    return "ts"


def _detect_drm(playlist, key) -> tuple[bool, bool]:
    """返回 (encrypted, drm)."""
    if key is None:
        return False, False
    method = (key.method or "").upper()
    if method in ("NONE", ""):
        return False, False
    if method in DRM_METHODS:
        return True, True
    uri = key.uri or ""
    if any(marker in uri.lower() for marker in DRM_HINT_MARKERS):
        return True, True
    if method == "AES-128":
        return True, False
    return True, method not in ("AES-128",)


def _title_from_url(url: str) -> str:
    path = urlparse(url).path if _is_url(url) else url
    name = os.path.splitext(os.path.basename(path))[0]
    return name or "未命名视频"


def parse_m3u8(source: str, title: str = "", timeout: int = DEFAULT_TIMEOUT) -> M3U8Info:
    """解析本地文件或网络 URL, 返回 M3U8Info.

    Master Playlist 会自动选择最佳变体继续解析。
    """
    if not source or not str(source).strip():
        raise ParseError("M3U8 地址为空")
    source = str(source).strip()

    if _is_url(source):
        content = _fetch_text(source)
    else:
        if not os.path.exists(source):
            raise ParseError(f"文件不存在: {source}")
        content = _read_local(source)

    base = _base_uri(source)
    try:
        playlist = m3u8.loads(content, uri=source if _is_url(source) else None)
    except Exception as exc:
        raise ParseError(f"m3u8语法错误: {exc}") from exc

    info = M3U8Info(url=source, raw_content=content, base_uri=base)
    info.title = title.strip() or _title_from_url(source)
    info.version = int(playlist.version or 0)
    info.target_duration = float(playlist.target_duration or 0)

    if playlist.is_variant:
        info.is_master = True
        info.variants = []
        for pl in playlist.playlists:
            stream_info = pl.stream_info or {}
            uri = pl.uri or ""
            if not _is_url(uri):
                uri = _resolve(uri, base)
            info.variants.append(
                VariantStream(
                    uri=uri,
                    bandwidth=int(getattr(stream_info, "bandwidth", 0) or 0),
                    resolution=_norm_resolution(getattr(stream_info, "resolution", "")),
                    codecs=str(getattr(stream_info, "codecs", "") or ""),
                    frame_rate=float(getattr(stream_info, "frame_rate", 0) or 0),
                    audio=str(getattr(stream_info, "audio", "") or ""),
                )
            )
        for media in playlist.media:
            if media.type == "AUDIO":
                info.media.append(
                    MediaInfo(
                        type=media.type or "AUDIO",
                        uri=_resolve(media.uri or "", base) if media.uri else "",
                        group_id=media.group_id or "",
                        name=media.name or "",
                        language=media.language or "",
                        default=bool(media.default),
                    )
                )
        best = _best_variant(info.variants)
        logger.info("Master Playlist: %s 个变体, 选择 %s (%s)", len(info.variants), best.resolution, best.bandwidth)
        child = parse_m3u8(best.uri, title=info.title, timeout=timeout)
        child.url = source
        child.title = info.title
        child.variants = info.variants
        child.media = info.media
        child.is_master = False
        if not child.resolution:
            child.resolution = best.resolution
        if not child.bandwidth:
            child.bandwidth = best.bandwidth
        if not child.codecs:
            child.codecs = best.codecs
        return child

    # ---- Media Playlist ----
    info.is_master = False
    info.segment_type = _detect_segment_type(playlist)

    total_duration = 0.0
    seq_start = int(playlist.media_sequence or 0)
    real_keys = [k for k in (playlist.keys or []) if k is not None]
    encrypted, drm = _detect_drm(playlist, real_keys[0] if real_keys else None)

    info.encrypted = encrypted
    info.drm = drm
    if real_keys:
        first_key = real_keys[0]
        info.key_method = (first_key.method or "").upper()
        info.key_url = _resolve(first_key.uri or "", base) if first_key.uri else ""

    for idx, seg in enumerate(playlist.segments):
        dur = float(seg.duration or 0)
        total_duration += dur
        seg_uri = seg.uri or ""
        if not _is_url(seg_uri):
            seg_uri = _resolve(seg_uri, base)
        seg_key_uri, seg_key_method, seg_key_iv = "", "", ""
        if seg.key is not None and (seg.key.method or "").upper() not in ("", "NONE"):
            seg_key_method = (seg.key.method or "").upper()
            seg_key_uri = _resolve(seg.key.uri or "", base) if seg.key.uri else ""
            seg_key_iv = str(seg.key.iv or "")
        info.segments.append(
            SegmentInfo(
                uri=seg_uri,
                duration=dur,
                byte_range=str(seg.byterange or ""),
                key_uri=_resolve(seg_key_uri, base) if seg_key_uri else "",
                key_method=seg_key_method,
                key_iv=seg_key_iv,
                sequence=seq_start + idx,
            )
        )

    if playlist.playlist_type == "VOD" or not playlist.is_endlist:
        pass
    info.duration = total_duration

    if not info.segments:
        raise ParseError("M3U8 中没有找到任何分片")

    if drm:
        raise DRMProtectedError(
            "该视频受到DRM数字版权保护(如Widevine/PlayReady), 本工具不提供也不支持任何破解能力。"
            "请通过官方授权渠道观看或下载。"
        )

    logger.info(
        "解析完成: %s | %s分片 | %s | 时长%.1fs | 加密=%s",
        info.title, info.segment_count, info.type_label, info.duration,
        f"{info.key_method}" if info.encrypted else "否",
    )
    return info


def get_audio_info(info: M3U8Info) -> str:
    """返回音频描述文本."""
    if info.media:
        parts = []
        for m in info.media:
            label = m.name or m.group_id or "音频"
            if m.language:
                label += f"({m.language})"
            parts.append(label)
        return ", ".join(parts)
    if info.codecs and "mp4a" in info.codecs:
        return "AAC (mp4a)"
    return "未知"


def probe_network_speed(url: str, sample_size: int = 256 * 1024) -> float:
    """抽样测速, 返回 bytes/s, 失败返回 0."""
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        downloaded = 0
        import time
        start = time.monotonic()
        for chunk in resp.iter_content(64 * 1024):
            downloaded += len(chunk)
            if downloaded >= sample_size or time.monotonic() - start > 5:
                break
        elapsed = max(time.monotonic() - start, 0.001)
        return downloaded / elapsed
    except Exception as exc:
        logger.debug("测速失败: %s", exc)
        return 0.0
