"""下载速度控制器(令牌桶, 线程安全).

所有下载线程共享一个 SpeedController 实例,
通过 acquire(n) 阻塞式获取配额实现全局限速。
"""

import logging
import threading
import time

logger = logging.getLogger("m3u8ToMp4.speed")

UNLIMITED = 0


class SpeedController:
    """令牌桶限速器. limit_bps<=0 表示不限速."""

    def __init__(self, limit_bps: int = UNLIMITED):
        self._lock = threading.Lock()
        self._limit = max(int(limit_bps), 0)
        self._tokens = float(self._limit) if self._limit > 0 else 0.0
        self._last_refill = time.monotonic()
        self._stop = threading.Event()
        self._rate = float(self._limit)
        self._measured_bps = 0.0
        self._measured_lock = threading.Lock()

    # ---------- 配置 ----------
    @property
    def limit(self) -> int:
        return self._limit

    def set_limit(self, limit_bps: int):
        with self._lock:
            self._limit = max(int(limit_bps), 0)
            self._rate = float(self._limit)
            if self._limit > 0:
                self._tokens = min(self._tokens, float(self._limit))
            logger.info("限速更新: %s B/s", self._limit)

    # ---------- 配额获取 ----------
    def acquire(self, nbytes: int, chunk_size: int = 64 * 1024):
        """阻塞直到允许传输 nbytes 字节. 不限速时立即返回."""
        if nbytes <= 0:
            return
        with self._lock:
            if self._limit <= 0:
                return
        while not self._stop.is_set():
            with self._lock:
                if self._limit <= 0:
                    return
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._last_refill = now
                self._tokens = min(self._tokens + elapsed * self._rate, self._rate)
                if self._tokens >= nbytes:
                    self._tokens -= nbytes
                    return
                need = nbytes - self._tokens
                wait = need / self._rate
            time.sleep(min(max(wait, 0.005), 0.2))
        # 停止信号
        return

    # ---------- 测量 ----------
    def record(self, nbytes: int):
        """记录实际传输字节数(用于统计显示)."""
        with self._measured_lock:
            self._measured_bps += nbytes

    def pop_speed(self) -> float:
        """返回自上次调用以来的平均速度(bytes/s)并清零."""
        with self._measured_lock:
            value = self._measured_bps
            self._measured_bps = 0.0
        return value

    def stop(self):
        self._stop.set()

    def resume(self):
        self._stop.clear()
