"""任务管理器: 队列调度、并发控制、暂停/恢复/重试、状态持久化."""

import logging
import os
import shutil
import uuid
from dataclasses import asdict

from PySide6.QtCore import QObject, QThread, Signal

from app.core.downloader import TaskState, TaskWorker
from app.core.speed_controller import SpeedController
from app.ui.settings import AppConfig
from app.ui.task_widget import TaskInfo

logger = logging.getLogger("m3u8ToMp4.taskmanager")

MAX_CONCURRENT_DEFAULT = 3


class ManagedTask:
    """受管理的任务包装."""

    def __init__(self, info: TaskInfo, worker: TaskWorker, thread: QThread):
        self.info = info
        self.worker = worker
        self.thread = thread
        self.paused = False

    @property
    def id(self) -> str:
        return self.info.id

    @property
    def running(self) -> bool:
        return self.thread.isRunning()


class TaskManager(QObject):
    """全局任务队列.

    - 维护等待队列与运行中任务
    - 依据 max_concurrent 自动调度
    - 向 UI 发出状态/进度/日志信号
    """

    task_status = Signal(str, str)                 # task_id, status
    task_progress = Signal(str, float, float, float, float)
    task_log = Signal(str, str)
    task_completed = Signal(str, str)
    task_failed = Signal(str, str)
    task_removed = Signal(str)
    queue_changed = Signal()

    def __init__(self, config: AppConfig | None = None, parent=None):
        super().__init__(parent)
        self.config = config or AppConfig()
        self.speed = SpeedController(self.config.speed_limit)
        self._pending: list[TaskInfo] = []
        self._active: dict[str, ManagedTask] = {}
        self._all: dict[str, TaskInfo] = {}
        self._history_hook = None   # 由 Phase 6 注入: fn(task_id, name, path, status)
        self._paused_waiting: list[TaskInfo] = []
        import sys

        if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
            self.cache_root = os.path.join(os.path.dirname(sys.executable), "download_cache")
        else:
            self.cache_root = os.path.join(os.getcwd(), "download_cache")
        os.makedirs(self.cache_root, exist_ok=True)
        logger.info("TaskManager 初始化, 并发=%s, 限速=%s", self.config.max_concurrent, self.config.speed_limit)

    # ---------- 配置 ----------
    def apply_settings(self):
        self.speed.set_limit(self.config.speed_limit)
        self._pump()

    def set_history_hook(self, hook):
        self._history_hook = hook

    # ---------- 任务操作 ----------
    def add_task(self, info: TaskInfo) -> bool:
        if info.id in self._all:
            logger.warning("任务已存在: %s", info.id)
            return False
        self._all[info.id] = info
        self._pending.append(info)
        logger.info("任务入队: %s (%s)", info.name, info.id)
        self.queue_changed.emit()
        self._pump()
        return True

    def start_task(self, task_id: str):
        info = self._all.get(task_id)
        if not info:
            return
        if task_id in self._active:
            return
        if info in self._paused_waiting:
            self._paused_waiting.remove(info)
        if info not in self._pending:
            self._pending.append(info)
        self.task_status.emit(task_id, "等待")
        self.queue_changed.emit()
        self._pump()

    def pause_task(self, task_id: str):
        mt = self._active.get(task_id)
        if mt and mt.running:
            mt.paused = True
            mt.worker.request_pause()
            self.task_status.emit(task_id, "暂停")
            logger.info("任务暂停: %s", task_id)
            return
        info = self._all.get(task_id)
        if info and info in self._pending:
            self._pending.remove(info)
            self.task_status.emit(task_id, "暂停")
            self._paused_waiting.append(info)
            self.queue_changed.emit()

    def resume_task(self, task_id: str):
        info = self._all.get(task_id)
        if not info:
            return
        if info in self._paused_waiting:
            self._paused_waiting.remove(info)
        if task_id in self._active:
            # worker 尚在运行(未到检查点), 通知其恢复
            mt = self._active[task_id]
            mt.paused = False
            mt.worker.request_resume()
            return
        if info not in self._pending:
            self._pending.append(info)
        self.task_status.emit(task_id, "等待")
        self.queue_changed.emit()
        self._pump()

    def retry_task(self, task_id: str):
        info = self._all.get(task_id)
        if not info:
            return
        # 清理失败状态, 重新入队(保留已完成分片以续传)
        if info in self._paused_waiting:
            self._paused_waiting.remove(info)
        if info not in self._pending:
            self._pending.append(info)
        self.task_status.emit(task_id, "等待")
        self.queue_changed.emit()
        self._pump()

    def remove_task(self, task_id: str, delete_cache: bool = True):
        mt = self._active.get(task_id)
        if mt:
            mt.worker.request_cancel()
            mt.thread.quit()
            mt.thread.wait(3000)
            self._active.pop(task_id, None)
        info = self._all.pop(task_id, None)
        if info in self._pending:
            self._pending.remove(info)
        if info in self._paused_waiting:
            self._paused_waiting.remove(info)
        if delete_cache:
            shutil.rmtree(os.path.join(self.cache_root, task_id), ignore_errors=True)
        self.task_removed.emit(task_id)
        self.queue_changed.emit()
        logger.info("任务移除: %s", task_id)
        self._pump()

    def stop_all(self):
        """程序退出时保存所有状态."""
        for task_id, mt in list(self._active.items()):
            mt.worker.request_cancel()
        for task_id, mt in list(self._active.items()):
            mt.thread.quit()
            mt.thread.wait(3000)
        self._active.clear()
        logger.info("所有任务已停止, 状态已保存")

    # ---------- 调度 ----------
    def _pump(self):
        max_c = max(1, int(self.config.max_concurrent or MAX_CONCURRENT_DEFAULT))
        while self._pending and len(self._active) < max_c:
            info = self._pending.pop(0)
            if info.id in self._active:
                continue
            self._launch(info)

    def _launch(self, info: TaskInfo):
        thread = QThread(self)
        worker = TaskWorker(
            task_id=info.id,
            name=info.name,
            url=info.url,
            download_dir=self.config.download_dir,
            cache_root=self.cache_root,
            speed=self.speed,
            config=self.config,
        )
        worker.threads = max(1, int(info.threads or 5))
        worker.referer = info.referer or ""
        worker.auto_convert = info.auto_convert if hasattr(info, "auto_convert") else self.config.auto_convert
        worker.output_format = info.output_format or self.config.output_format
        worker.moveToThread(thread)
        thread.started.connect(worker.run)

        worker.status_changed.connect(self._on_status)
        worker.progress_changed.connect(self._on_progress)
        worker.log_emitted.connect(self._on_log)
        worker.completed.connect(self._on_completed)
        worker.failed.connect(self._on_failed)

        mt = ManagedTask(info, worker, thread)
        self._active[info.id] = mt
        thread.finished.connect(lambda tid=info.id: self._on_thread_finished(tid))
        thread.start()
        self.task_status.emit(info.id, "解析中")
        logger.info("任务启动: %s", info.name)
        self.queue_changed.emit()

    # ---------- 信号转发 ----------
    def _on_status(self, task_id: str, status: str):
        info = self._all.get(task_id)
        if info:
            info.status = status
        self.task_status.emit(task_id, status)

    def _on_progress(self, task_id: str, pct: float, speed: float, downloaded: float, eta: float):
        info = self._all.get(task_id)
        if info:
            info.progress = pct
            info.speed = speed
            info.downloaded_size = downloaded
            info.eta = eta
        self.task_progress.emit(task_id, pct, speed, downloaded, eta)

    def _on_log(self, task_id: str, message: str):
        self.task_log.emit(task_id, message)

    def _on_completed(self, task_id: str, output_path: str):
        info = self._all.get(task_id)
        if info:
            info.status = "完成"
            info.progress = 100.0
            info.speed = 0.0
            info.file_path = output_path
        self.task_completed.emit(task_id, output_path)
        logger.info("任务完成: %s -> %s", task_id, output_path)

    def _on_failed(self, task_id: str, reason: str):
        info = self._all.get(task_id)
        if info:
            info.status = "失败"
            info.speed = 0.0
        self.task_failed.emit(task_id, reason)
        logger.warning("任务失败: %s - %s", task_id, reason)

    def _on_thread_finished(self, task_id: str):
        mt = self._active.get(task_id)
        if mt:
            mt.worker.deleteLater()
            mt.thread.deleteLater()
            self._active.pop(task_id, None)
        # 完成/失败/暂停后从等待队列也移除
        info = self._all.get(task_id)
        if info and info in self._pending:
            self._pending.remove(info)
        self.queue_changed.emit()
        self._pump()

    # ---------- 查询 ----------
    def running_count(self) -> int:
        return len(self._active)

    def pending_count(self) -> int:
        return len(self._pending)

    def all_tasks(self) -> list[TaskInfo]:
        return list(self._all.values())

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._all.get(task_id)

    def restore_pending(self, infos: list[TaskInfo]):
        """程序启动时恢复未完成任务."""
        for info in infos:
            if info.id in self._all:
                continue
            self._all[info.id] = info
            if info.status in ("下载中", "合并中", "转换中", "解析中"):
                info.status = "等待"
            if info.status == "等待":
                self._pending.append(info)
        self.queue_changed.emit()
        self._pump()
        logger.info("恢复 %s 个未完成任务", len(infos))
