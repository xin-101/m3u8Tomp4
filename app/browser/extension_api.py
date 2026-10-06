"""浏览器插件本地 API 服务.

Chrome Extension 通过 POST http://127.0.0.1:18888/api/task
提交检测到的 M3U8 地址, 本服务将其交给任务管理器自动创建任务。
"""

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger("m3u8ToMp4.extension")

DEFAULT_PORT = 18888


class ExtensionSignals(QObject):
    task_requested = Signal(str, str, str)   # url, title, referer
    error = Signal(str)


class _Handler(BaseHTTPRequestHandler):
    server_version = "m3u8ToMp4/1.0"
    signals: ExtensionSignals | None = None

    def log_message(self, fmt: str, *args):
        logger.debug("API %s", fmt % args)

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/health"):
            self._send_json(200, {"ok": True, "app": "m3u8ToMp4"})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.startswith("/api/task"):
            self._handle_task()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def _handle_task(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            data = json.loads(raw)
            url = str(data.get("url", "")).strip()
            title = str(data.get("title", "")).strip()
            referer = str(data.get("referer", "")).strip()
            lower = url.lower()
            looks_m3u8 = lower.endswith(".m3u8") or lower.endswith(".m3u") or ".m3u8" in lower
            if not url or not looks_m3u8:
                self._send_json(400, {"ok": False, "error": "url 必须是 m3u8 地址"})
                return
            signals = getattr(self.server, "signals", None)
            if signals is not None:
                signals.task_requested.emit(url, title, referer)
            logger.info("插件任务请求: %s (%s)", title or url, url)
            self._send_json(200, {"ok": True, "message": "已加入下载队列"})
        except json.JSONDecodeError:
            self._send_json(400, {"ok": False, "error": "JSON 解析失败"})
        except Exception as exc:
            logger.warning("API 处理异常: %s", exc)
            self._send_json(500, {"ok": False, "error": str(exc)})


class ExtensionApiServer:
    """本地 API 服务(后台线程运行)."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.signals = ExtensionSignals()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if self._server is not None:
            return True
        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
            server.signals = self.signals  # type: ignore[attr-defined]
            self._server = server
            self._thread = threading.Thread(target=server.serve_forever, daemon=True, name="extension-api")
            self._thread.start()
            logger.info("插件 API 服务已启动: http://127.0.0.1:%s", self.port)
            return True
        except OSError as exc:
            logger.error("插件 API 启动失败(端口可能被占用): %s", exc)
            self.signals.error.emit(str(exc))
            return False

    def stop(self):
        if self._server:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None
        self._thread = None
        logger.info("插件 API 服务已停止")

    @property
    def running(self) -> bool:
        return self._server is not None
