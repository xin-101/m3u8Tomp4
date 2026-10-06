import logging
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QStatusBar,
    QPlainTextEdit,
    QDialogButtonBox,
)

from app.ui.task_widget import TaskPage
from app.ui.settings import SettingsDialog
from app.ui.history_page import HistoryPage

logger = logging.getLogger("m3u8ToMp4.ui")

APP_STYLE = """
* {
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#centralWidget {
    background-color: #1e1f22;
}
QLabel {
    color: #d7d8db;
}
QLabel#appTitle {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
}
QLabel#appSubtitle {
    color: #8a8f98;
    font-size: 11px;
}
QFrame#topBar {
    background-color: #26272b;
    border-bottom: 1px solid #33353a;
}
QFrame#bottomBar {
    background-color: #26272b;
    border-top: 1px solid #33353a;
}
QPushButton#navButton {
    background-color: transparent;
    color: #b8bbc2;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 7px 14px;
}
QPushButton#navButton:hover {
    background-color: #33353a;
    color: #ffffff;
}
QPushButton#primaryButton {
    background-color: #3b82f6;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
}
QPushButton#primaryButton:hover {
    background-color: #2f6fe0;
}
QPushButton#primaryButton:pressed {
    background-color: #2559c4;
}
QTableWidget {
    background-color: #26272b;
    alternate-background-color: #2b2d31;
    color: #d7d8db;
    gridline-color: #33353a;
    border: 1px solid #33353a;
    border-radius: 8px;
    selection-background-color: #3b82f6;
    selection-color: #ffffff;
}
QTableWidget::item {
    padding: 6px 4px;
    border: none;
}
QHeaderView::section {
    background-color: #2f3136;
    color: #9ea2ab;
    border: none;
    border-bottom: 1px solid #3a3d43;
    padding: 8px 6px;
    font-weight: bold;
}
QTableCornerButton::section {
    background-color: #2f3136;
    border: none;
}
QProgressBar {
    background-color: #3a3d43;
    border: none;
    border-radius: 4px;
    height: 16px;
    text-align: center;
    color: #ffffff;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: #3b82f6;
    border-radius: 4px;
}
QPushButton#actionButton {
    background-color: #33353a;
    color: #d7d8db;
    border: 1px solid #44474e;
    border-radius: 4px;
    padding: 4px 10px;
}
QPushButton#actionButton:hover {
    background-color: #3b82f6;
    border-color: #3b82f6;
    color: #ffffff;
}
QLabel#statusValue {
    color: #ffffff;
    font-weight: bold;
}
QLabel#statusKey {
    color: #8a8f98;
}
QDialog, QWidget#settingsBody {
    background-color: #1e1f22;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #2b2d31;
    color: #d7d8db;
    border: 1px solid #44474e;
    border-radius: 5px;
    padding: 6px 8px;
    selection-background-color: #3b82f6;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border-color: #3b82f6;
}
QCheckBox {
    color: #d7d8db;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #55585f;
    background-color: #2b2d31;
}
QCheckBox::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
}
QGroupBox {
    color: #d7d8db;
    border: 1px solid #33353a;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #9ea2ab;
}
QTabWidget::pane {
    border: 1px solid #33353a;
    border-radius: 8px;
    background-color: #26272b;
}
QTabBar::tab {
    background-color: #2b2d31;
    color: #9ea2ab;
    padding: 8px 20px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #3b82f6;
    color: #ffffff;
}
QScrollBar:vertical {
    background-color: #1e1f22;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #44474e;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #3b82f6;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0;
}
QScrollBar:horizontal {
    background-color: #1e1f22;
    height: 10px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background-color: #44474e;
    border-radius: 5px;
    min-width: 30px;
}
QMenu {
    background-color: #2b2d31;
    color: #d7d8db;
    border: 1px solid #44474e;
}
QMenu::item:selected {
    background-color: #3b82f6;
}
QListWidget {
    background-color: #26272b;
    color: #d7d8db;
    border: 1px solid #33353a;
    border-radius: 8px;
}
QToolTip {
    background-color: #2b2d31;
    color: #d7d8db;
    border: 1px solid #44474e;
}
"""


def make_logo_pixmap(size: int = 34) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(QColor("#3b82f6"))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(0, 0, size, size, 8, 8)
    painter.setPen(QColor("#ffffff"))
    font = QFont()
    font.setBold(True)
    font.setPixelSize(int(size * 0.42))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "M4")
    painter.end()
    return pixmap


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("m3u8ToMp4 - M3U8视频下载与转换")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        self.setWindowIcon(QIcon(make_logo_pixmap(48)))
        self._log_lines: list[str] = []
        self._db = None
        self._build_ui()
        self._init_manager()
        self.setStyleSheet(APP_STYLE)
        self._start_status_timer()
        self._restore_unfinished()
        logger.info("主窗口初始化完成")

    def _init_manager(self):
        """创建任务管理器并接线."""
        from app.core.task_manager import TaskManager

        self.manager = TaskManager(parent=self)
        # UI → 管理器
        self.task_page.task_created.connect(self._on_task_created)
        self.task_page.action_requested.connect(self._on_task_action)
        self.history_page.redownload_requested.connect(self._on_redownload)
        # 管理器 → UI
        self.manager.task_status.connect(self._on_manager_status)
        self.manager.task_progress.connect(self._on_manager_progress)
        self.manager.task_log.connect(self._on_manager_log)
        self.manager.task_completed.connect(self._on_manager_completed)
        self.manager.task_failed.connect(self._on_manager_failed)

    # ---------- 任务生命周期 ----------
    def _on_task_created(self, info):
        self.manager.add_task(info)
        self._db_upsert(info)

    def _on_task_action(self, task_id: str, action: str):
        try:
            if action == "start":
                info = self.manager.get_task(task_id)
                if info and info.status == "失败":
                    self.manager.retry_task(task_id)
                else:
                    self.manager.start_task(task_id)
            elif action == "pause":
                self.manager.pause_task(task_id)
            elif action == "remove":
                self.manager.remove_task(task_id)
                self.task_page.remove_task(task_id)
                self._db_delete(task_id)
        except Exception as exc:
            logger.exception("任务操作失败: %s/%s", task_id, action)
            QMessageBox.warning(self, "操作失败", str(exc))

    def _on_redownload(self, url: str, name: str):
        self._switch_page(0)
        self.task_page.prompt_new_task_with(url, name)

    def _on_manager_status(self, task_id: str, status: str):
        self.task_page.update_task(task_id, status=status)
        self._db_update_status(task_id, status)

    def _on_manager_progress(self, task_id: str, pct: float, speed: float,
                             downloaded: float, eta: float):
        self.task_page.update_task(task_id, progress=pct, speed=speed,
                                   downloaded_size=downloaded, eta=eta)

    def _on_manager_log(self, task_id: str, message: str):
        from datetime import datetime
        line = f"{datetime.now().strftime('%H:%M:%S')} [{task_id[:6]}] {message}"
        self._log_lines.append(line)
        if len(self._log_lines) > 500:
            self._log_lines = self._log_lines[-500:]
        if hasattr(self, "_log_view") and self._log_view is not None:
            self._log_view.appendPlainText(line)

    def _on_manager_completed(self, task_id: str, output_path: str):
        info = self.manager.get_task(task_id)
        self.task_page.update_task(task_id, status="完成", progress=100.0,
                                   speed=0.0, file_path=output_path, eta=-1)
        try:
            from app.database.sqlite import Database

            db = self._get_db()
            size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            db.add_history(
                file_name=os.path.basename(output_path),
                size=size,
                download_path=output_path,
                source_url=info.url if info else "",
                duration=info.duration if info else 0,
                status="完成",
                task_id=task_id,
            )
            db.update_task_status(task_id, "完成", 100.0, output_path)
            db.delete_task(task_id)
            if self.content.currentIndex() == 1:
                self.history_page.refresh()
        except Exception:
            logger.exception("写入历史失败")
        self._on_manager_log(task_id, f"完成 -> {output_path}")

    def _on_manager_failed(self, task_id: str, reason: str):
        self.task_page.update_task(task_id, status="失败", speed=0.0)
        self._db_update_status(task_id, "失败", error=reason)
        self._on_manager_log(task_id, f"失败: {reason}")

    # ---------- 数据库辅助 ----------
    def _get_db(self):
        if self._db is None:
            from app.database.sqlite import Database

            self._db = Database()
        return self._db

    def _db_upsert(self, info):
        try:
            self._get_db().upsert_task({
                "id": info.id, "url": info.url, "name": info.name,
                "path": info.file_path, "size": info.total_size,
                "duration": info.duration, "status": info.status,
                "progress": info.progress, "segment_count": info.segment_count,
                "resolution": info.resolution, "referer": info.referer,
                "auto_convert": int(info.auto_convert),
                "output_format": info.output_format,
                "threads": info.threads,
            })
        except Exception:
            logger.debug("任务入库失败", exc_info=True)

    def _db_update_status(self, task_id: str, status: str, error: str = ""):
        try:
            info = self.manager.get_task(task_id)
            self._get_db().update_task_status(
                task_id, status,
                progress=info.progress if info else None,
                error=error,
            )
        except Exception:
            logger.debug("任务状态入库失败", exc_info=True)

    def _db_delete(self, task_id: str):
        try:
            self._get_db().delete_task(task_id)
        except Exception:
            logger.debug("任务删除失败", exc_info=True)

    def _restore_unfinished(self):
        """启动时恢复未完成任务."""
        try:
            from app.database.sqlite import Database
            from app.ui.task_widget import TaskInfo

            rows = Database().get_unfinished_tasks()
            infos = []
            for row in rows:
                if not row.get("url"):
                    continue
                info = TaskInfo(
                    id=row["id"], name=row.get("name") or "未命名视频",
                    url=row["url"], status="等待",
                    duration=row.get("duration", 0) or 0,
                    resolution=row.get("resolution", "") or "",
                    segment_count=row.get("segment_count", 0) or 0,
                    referer=row.get("referer", "") or "",
                    auto_convert=bool(row.get("auto_convert", 1)),
                    output_format=row.get("output_format", "mp4") or "mp4",
                    threads=row.get("threads", 5) or 5,
                )
                infos.append(info)
            for info in infos:
                self.task_page.add_task(info)
            if infos:
                self.manager.restore_pending(infos)
                self._on_manager_log("--", f"已恢复 {len(infos)} 个未完成任务(点击开始继续)")
        except Exception:
            logger.exception("恢复任务失败")

    # ---------- UI 构建 ----------

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())

        self.content = QStackedWidget()
        self.task_page = TaskPage()
        self.history_page = HistoryPage()
        self.content.addWidget(self.task_page)
        self.content.addWidget(self.history_page)
        root_layout.addWidget(self.content, 1)

        root_layout.addWidget(self._build_bottom_bar())
        self.setCentralWidget(central)

    def _build_top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("topBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        logo = QLabel()
        logo.setPixmap(make_logo_pixmap(34))
        logo.setFixedSize(34, 34)
        layout.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("m3u8ToMp4")
        title.setObjectName("appTitle")
        subtitle = QLabel("M3U8 下载 · 合并 · 转换")
        subtitle.setObjectName("appSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        layout.addLayout(title_box)
        layout.addStretch(1)

        self.btn_new_task = QPushButton("新建任务")
        self.btn_new_task.setObjectName("primaryButton")
        self.btn_new_task.setCursor(Qt.PointingHandCursor)
        self.btn_new_task.clicked.connect(self._on_new_task)

        self.btn_batch = QPushButton("批量添加")
        self.btn_batch.setObjectName("navButton")
        self.btn_batch.setCursor(Qt.PointingHandCursor)
        self.btn_batch.clicked.connect(self._on_batch_add)

        self.btn_history = QPushButton("历史记录")
        self.btn_history.setObjectName("navButton")
        self.btn_history.setCursor(Qt.PointingHandCursor)
        self.btn_history.clicked.connect(lambda: self._switch_page(1))

        self.btn_tasks = QPushButton("下载任务")
        self.btn_tasks.setObjectName("navButton")
        self.btn_tasks.setCursor(Qt.PointingHandCursor)
        self.btn_tasks.clicked.connect(lambda: self._switch_page(0))

        self.btn_settings = QPushButton("设置")
        self.btn_settings.setObjectName("navButton")
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self._on_settings)

        for btn in (self.btn_tasks, self.btn_new_task, self.btn_batch, self.btn_history, self.btn_settings):
            layout.addWidget(btn)
        return bar

    def _build_bottom_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("bottomBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 7, 16, 7)
        layout.setSpacing(22)

        self.label_speed_key = QLabel("当前速度:")
        self.label_speed_key.setObjectName("statusKey")
        self.label_speed = QLabel("0 B/s")
        self.label_speed.setObjectName("statusValue")

        self.label_space_key = QLabel("剩余空间:")
        self.label_space_key.setObjectName("statusKey")
        self.label_space = QLabel("--")
        self.label_space.setObjectName("statusValue")

        self.label_tasks_key = QLabel("任务:")
        self.label_tasks_key.setObjectName("statusKey")
        self.label_tasks = QLabel("0")
        self.label_tasks.setObjectName("statusValue")

        self._log_view = None
        self.btn_log = QPushButton("查看日志")
        self.btn_log.setObjectName("actionButton")
        self.btn_log.setCursor(Qt.PointingHandCursor)
        self.btn_log.clicked.connect(self._show_log_window)

        layout.addWidget(self.label_speed_key)
        layout.addWidget(self.label_speed)
        layout.addWidget(self.label_space_key)
        layout.addWidget(self.label_space)
        layout.addWidget(self.label_tasks_key)
        layout.addWidget(self.label_tasks)
        layout.addStretch(1)
        layout.addWidget(self.btn_log)
        return bar

    def _show_log_window(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("运行日志")
        dialog.setMinimumSize(760, 460)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText("\n".join(self._log_lines[-500:]))
        view.setStyleSheet("background-color: #141518; color: #b8bbc2; font-family: Consolas, monospace;")
        layout.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        self._log_view = view
        dialog.finished.connect(lambda *_: setattr(self, "_log_view", None))
        dialog.exec()

    def closeEvent(self, event):
        """关闭时保存任务状态并停止所有下载."""
        try:
            running = self.manager.running_count() + self.manager.pending_count()
            if running > 0:
                ret = QMessageBox.question(
                    self, "退出确认",
                    f"当前有 {running} 个任务未完成, 退出将保存进度(下次启动可继续)。\n确定退出?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if ret != QMessageBox.Yes:
                    event.ignore()
                    return
            self.manager.stop_all()
            # 持久化所有活跃任务
            for info in self.manager.all_tasks():
                if info.status not in ("完成",):
                    self._db_upsert(info)
            logger.info("应用退出, 任务状态已保存")
        except Exception:
            logger.exception("退出清理失败")
        event.accept()

    def _switch_page(self, index: int):
        self.content.setCurrentIndex(index)
        if index == 1:
            self.history_page.refresh()
        logger.debug("切换到页面 %s", index)

    def _on_new_task(self):
        self.task_page.prompt_new_task()

    def _on_batch_add(self):
        self.task_page.prompt_batch_add()

    def _on_settings(self):
        dialog = SettingsDialog(self, config=self.manager.config)
        if dialog.exec() == QDialog.Accepted:
            try:
                self.manager.apply_settings()
                self._on_manager_log("--", "设置已保存并生效")
            except Exception:
                logger.exception("应用设置失败")
            QMessageBox.information(self, "设置", "设置已保存并生效")

    def _start_status_timer(self):
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._update_status_bar)
        self._status_timer.start()
        self._update_status_bar()

    def _update_status_bar(self):
        try:
            import shutil
            from app.ui.task_widget import format_size

            total_speed = self.task_page.current_total_speed()
            self.label_speed.setText(format_size(total_speed) + "/s")
            free = shutil.disk_usage(".").free
            self.label_space.setText(format_size(free))
            self.label_tasks.setText(str(self.task_page.task_count()))
        except Exception as exc:
            logger.debug("状态栏更新失败: %s", exc)
