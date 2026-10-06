"""Phase 3-5 核心链路集成测试.

1. FFmpeg 本地 m3u8 转 MP4
2. HTTP 服务器提供 m3u8, 走完整下载→合并→转换链路
3. 暂停/断点续传验证
"""

import http.server
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QCoreApplication, QTimer  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MEDIA = os.path.join(ROOT, "tests", "media")
DOWNLOAD_DIR = os.path.join(ROOT, "tests", "out")
CACHE_ROOT = os.path.join(ROOT, "tests", "cache")

results = []


def report(name: str, ok: bool, detail: str = ""):
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=MEDIA, **kwargs)

    def log_message(self, *args):
        pass


def start_server() -> tuple[http.server.ThreadingHTTPServer, int]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def wait_until(cond, timeout: float = 60.0, interval: float = 0.2) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return False


def test_ffmpeg_local_convert(app):
    """本地 m3u8 → MP4 (TaskWorker local_input 路径)."""
    from app.core.downloader import TaskWorker
    from app.core.speed_controller import SpeedController

    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    src = os.path.join(MEDIA, "index.m3u8")
    worker = TaskWorker(
        task_id="local001", name="本地转换测试", url=src,
        download_dir=DOWNLOAD_DIR, cache_root=CACHE_ROOT,
        speed=SpeedController(0),
    )
    worker.auto_convert = True
    worker.output_format = "mp4"
    events = {"done": False, "ok": False, "path": "", "error": "", "status": ""}
    worker.completed.connect(lambda tid, path: events.update(done=True, ok=True, path=path))
    worker.failed.connect(lambda tid, r: events.update(done=True, error=r))
    worker.status_changed.connect(lambda tid, s: events.update(status=s))
    worker.run()
    ok = events["done"] and events["ok"] and os.path.exists(events["path"])
    size = os.path.getsize(events["path"]) if ok else 0
    report("本地m3u8转MP4", ok and size > 100000, f"size={size} status={events['status']} err={events['error'][:120]}")
    return events["path"] if ok else None


def test_http_download_full(app, port: int):
    """网络下载完整链路."""
    from app.core.downloader import TaskWorker
    from app.core.speed_controller import SpeedController

    shutil.rmtree(os.path.join(CACHE_ROOT, "net001"), ignore_errors=True)
    url = f"http://127.0.0.1:{port}/index.m3u8"
    worker = TaskWorker(
        task_id="net001", name="网络下载测试", url=url,
        download_dir=DOWNLOAD_DIR, cache_root=CACHE_ROOT,
        speed=SpeedController(0),
    )
    worker.auto_convert = True
    worker.threads = 3
    events = {"done": False, "ok": False, "path": "", "error": "", "progress": 0.0, "speed": 0.0, "status": ""}
    worker.completed.connect(lambda tid, path: events.update(done=True, ok=True, path=path))
    worker.failed.connect(lambda tid, r: events.update(done=True, error=r))
    worker.status_changed.connect(lambda tid, s: events.update(status=s))
    worker.progress_changed.connect(lambda tid, pct, sp, dl, eta: events.update(progress=pct, speed=sp))
    worker.run()
    ok = events["done"] and events["ok"] and os.path.exists(events["path"])
    size = os.path.getsize(events["path"]) if ok else 0
    report("网络m3u8下载转换", ok and size > 100000,
           f"size={size} progress={events['progress']:.0f}% err={events['error'][:120]}")
    return events["path"] if ok else None


def test_pause_resume(app, port: int):
    """暂停→状态保存→续传完成."""
    from app.core.downloader import TaskState, TaskWorker
    from app.core.speed_controller import SpeedController

    task_id = "resume001"
    cache_dir = os.path.join(CACHE_ROOT, task_id)
    shutil.rmtree(cache_dir, ignore_errors=True)
    url = f"http://127.0.0.1:{port}/index.m3u8"

    # 阶段1: 慢速下载, 中途暂停
    worker = TaskWorker(
        task_id=task_id, name="续传测试", url=url,
        download_dir=DOWNLOAD_DIR, cache_root=CACHE_ROOT,
        speed=SpeedController(150 * 1024),   # 150KB/s 限速, 制造暂停时机
    )
    worker.threads = 1
    events = {"status": ""}
    worker.status_changed.connect(lambda tid, s: events.update(status=s))
    # 主线程直接 run()(与产品一致的 direct 信号), Timer 线程触发暂停
    import threading as th
    pause_timer = th.Timer(0.4, worker.request_pause)
    pause_timer.start()
    worker.run()
    state = TaskState.load(cache_dir)
    if state is None:
        report("暂停状态保存", False, "state.json 不存在")
        return False
    done1 = state.done_count()
    report("限速+暂停", done1 < state.total_segments and events["status"] == "暂停",
           f"done={done1}/{state.total_segments} status={events['status']}")

    # 阶段2: 恢复不限速, 续传完成
    worker2 = TaskWorker(
        task_id=task_id, name="续传测试", url=url,
        download_dir=DOWNLOAD_DIR, cache_root=CACHE_ROOT,
        speed=SpeedController(0),
    )
    worker2.threads = 3
    ev2 = {"done": False, "ok": False, "path": "", "error": ""}
    worker2.completed.connect(lambda tid, path: ev2.update(done=True, ok=True, path=path))
    worker2.failed.connect(lambda tid, r: ev2.update(done=True, error=r))
    worker2.run()
    ok = ev2["ok"] and os.path.exists(ev2["path"])
    state2 = TaskState.load(cache_dir)
    cache_cleaned = state2 is None  # 完成后应清理缓存
    size = os.path.getsize(ev2["path"]) if ok else 0
    report("断点续传完成", ok and size > 100000, f"size={size} cache_cleaned={cache_cleaned} err={ev2['error'][:100]}")
    return ok


def test_speed_limiter():
    """限速器精度粗测."""
    import threading as th
    from app.core.speed_controller import SpeedController

    sc = SpeedController(200 * 1024)  # 200KB/s
    total = 0
    lock = th.Lock()

    def eat():
        nonlocal total
        for _ in range(20):
            sc.acquire(32 * 1024)
            with lock:
                total += 32 * 1024
            sc.record(32 * 1024)

    threads = [th.Thread(target=eat) for _ in range(3)]
    start = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    elapsed = time.monotonic() - start
    speed = total / elapsed
    ok = 100 * 1024 <= speed <= 420 * 1024
    report("限速器精度", ok, f"total={total//1024}KB elapsed={elapsed:.2f}s avg={speed/1024:.0f}KB/s (目标200)")
    return ok


def main():
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(CACHE_ROOT, exist_ok=True)
    app = QCoreApplication(sys.argv)

    print("== Phase3-5 核心链路测试 ==")
    server, port = start_server()
    print(f"  HTTP服务器: 127.0.0.1:{port}")

    test_speed_limiter()
    test_ffmpeg_local_convert(app)
    test_http_download_full(app, port)
    test_pause_resume(app, port)

    server.shutdown()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n结果: {passed} 通过, {failed} 失败")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAILED: {name} - {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
