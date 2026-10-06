import logging
import os
import re
import uuid
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QDialog,
    QDialogButtonBox,
    QCheckBox,
)

logger = logging.getLogger("m3u8ToMp4.task")

ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')

STATUS_COLORS = {
    "等待": "#8a8f98",
    "解析中": "#f59e0b",
    "下载中": "#3b82f6",
    "暂停": "#a855f7",
    "合并中": "#06b6d4",
    "转换中": "#f97316",
    "完成": "#22c55e",
    "失败": "#ef4444",
}


def format_size(size_bytes: float) -> str:
    if size_bytes is None or size_bytes < 0:
        return "--"
    units = ["B", "KB", "MB", "GB", "TB"]
    index = 0
    value = float(size_bytes)
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.2f} {units[index]}" if index > 0 else f"{value:.0f} {units[index]}"


def sanitize_filename(name: str, default: str = "未命名视频") -> str:
    name = ILLEGAL_CHARS.sub("_", name).strip().strip(".")
    return name[:120] if name else default


def format_eta(seconds: float) -> str:
    if seconds is None or seconds < 0 or seconds != seconds:
        return "--"
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


@dataclass
class TaskInfo:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = "未命名视频"
    url: str = ""
    status: str = "等待"
    progress: float = 0.0
    total_size: float = -1
    downloaded_size: float = 0.0
    speed: float = 0.0
    eta: float = -1
    file_path: str = ""
    duration: float = 0.0
    resolution: str = ""
    segment_count: int = 0
    segment_type: str = "ts"
    encrypted: bool = False
    key_method: str = ""
    key_url: str = ""
    auto_convert: bool = True
    threads: int = 5
    referer: str = ""
    output_format: str = "mp4"


class NewTaskDialog(QDialog):
    def __init__(self, parent=None, default_dir: str = ""):
        super().__init__(parent)
        self.setWindowTitle("新建下载任务")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.input_url = QLineEdit()
        self.input_url.setPlaceholderText("输入 M3U8 地址, 例如 https://xxx.com/video/index.m3u8")
        layout.addWidget(QLabel("M3U8 地址:"))
        layout.addWidget(self.input_url)

        file_row = QHBoxLayout()
        self.input_file = QLineEdit()
        self.input_file.setPlaceholderText("或选择本地 .m3u8 文件")
        btn_browse = QPushButton("浏览...")
        btn_browse.setObjectName("actionButton")
        btn_browse.clicked.connect(self._browse_file)
        file_row.addWidget(self.input_file, 1)
        file_row.addWidget(btn_browse)
        layout.addLayout(file_row)

        self.input_name = QLineEdit()
        self.input_name.setPlaceholderText("留空则自动根据元数据命名")
        layout.addWidget(QLabel("视频名称:"))
        layout.addWidget(self.input_name)

        self.check_convert = QCheckBox("下载完成后自动转换为 MP4")
        self.check_convert.setChecked(True)
        layout.addWidget(self.check_convert)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("创建任务")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.accepted.connect(self._validate_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.auto_convert = True

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择M3U8文件", "", "M3U8文件 (*.m3u8);;所有文件 (*)")
        if path:
            self.input_file.setText(path)
            if not self.input_name.text():
                self.input_name.setText(os.path.splitext(os.path.basename(path))[0])

    def _validate_accept(self):
        if not self.input_url.text().strip() and not self.input_file.text().strip():
            QMessageBox.warning(self, "提示", "请输入 M3U8 地址或选择本地文件")
            return
        self.auto_convert = self.check_convert.isChecked()
        self.accept()

    def get_task(self) -> TaskInfo:
        url = self.input_url.text().strip() or self.input_file.text().strip()
        name = sanitize_filename(self.input_name.text().strip() or os.path.splitext(os.path.basename(url))[0])
        return TaskInfo(name=name, url=url)


class TaskPage(QWidget):
    task_created = Signal(object)
    action_requested = Signal(str, str)   # task_id, start|pause|remove|retry

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: dict[str, TaskInfo] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("下载任务")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        header.addWidget(title)
        header.addStretch(1)
        self.label_empty_hint = QLabel("点击右上角「新建任务」开始下载")
        self.label_empty_hint.setObjectName("appSubtitle")
        header.addWidget(self.label_empty_hint)
        layout.addLayout(header)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["名称", "大小", "速度", "进度", "剩余时间", "状态", "操作"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in range(1, 7):
            header_view.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header_view.setStretchLastSection(False)
        layout.addWidget(self.table, 1)

        self.empty_label = QLabel("暂无任务")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setStyleSheet("color: #55585f; font-size: 15px;")
        layout.addWidget(self.empty_label)
        self._update_empty_state()

    # ---------- 任务操作 ----------
    def add_task(self, info: TaskInfo) -> TaskInfo:
        self._tasks[info.id] = info
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(info.name))
        self.table.item(row, 0).setData(Qt.UserRole, info.id)
        self.table.setItem(row, 1, QTableWidgetItem(format_size(info.total_size)))
        self.table.setItem(row, 2, QTableWidgetItem("--"))
        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(0)
        progress.setTextVisible(True)
        self.table.setCellWidget(row, 3, progress)
        self.table.setItem(row, 4, QTableWidgetItem("--"))
        status_item = QTableWidgetItem(info.status)
        status_item.setForeground(QColor(STATUS_COLORS.get(info.status, "#d7d8db")))
        status_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, 5, status_item)
        self.table.setCellWidget(row, 6, self._build_action_buttons(info.id))
        self._update_empty_state()
        logger.info("任务已创建: %s (%s)", info.name, info.id)
        return info

    def _build_action_buttons(self, task_id: str) -> QWidget:
        container = QWidget()
        h = QHBoxLayout(container)
        h.setContentsMargins(4, 4, 4, 4)
        h.setSpacing(6)
        btn_start = QPushButton("开始")
        btn_start.setObjectName("actionButton")
        btn_start.setCursor(Qt.PointingHandCursor)
        btn_start.clicked.connect(lambda: self._on_action(task_id, "start"))
        btn_pause = QPushButton("暂停")
        btn_pause.setObjectName("actionButton")
        btn_pause.setCursor(Qt.PointingHandCursor)
        btn_pause.clicked.connect(lambda: self._on_action(task_id, "pause"))
        btn_remove = QPushButton("删除")
        btn_remove.setObjectName("actionButton")
        btn_remove.setCursor(Qt.PointingHandCursor)
        btn_remove.clicked.connect(lambda: self._on_action(task_id, "remove"))
        h.addWidget(btn_start)
        h.addWidget(btn_pause)
        h.addWidget(btn_remove)
        return container

    def _on_action(self, task_id: str, action: str):
        info = self._tasks.get(task_id)
        if not info:
            return
        if action == "remove":
            ret = QMessageBox.question(self, "删除任务", f"确定删除任务「{info.name}」?")
            if ret != QMessageBox.Yes:
                return
            self.action_requested.emit(task_id, "remove")
            logger.info("请求删除任务: %s", task_id)
        elif action == "start":
            # 状态为暂停/失败/等待时 开始=恢复或重试
            self.action_requested.emit(task_id, "start")
        elif action == "pause":
            self.action_requested.emit(task_id, "pause")

    def _show_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        item = self.table.item(row, 0)
        if not item:
            return
        task_id = item.data(Qt.UserRole)
        menu = QMenu(self)
        menu.addAction("复制链接", lambda: self._copy_url(task_id))
        menu.addAction("打开文件位置", lambda: self._open_location(task_id))
        menu.addSeparator()
        menu.addAction("删除任务", lambda: self._on_action(task_id, "remove"))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy_url(self, task_id: str):
        info = self._tasks.get(task_id)
        if info and info.url:
            QApplication.clipboard().setText(info.url)
            logger.info("已复制链接: %s", info.url)

    def _open_location(self, task_id: str):
        info = self._tasks.get(task_id)
        if info and info.file_path and os.path.exists(info.file_path):
            os.startfile(os.path.dirname(info.file_path))
        else:
            QMessageBox.information(self, "提示", "文件尚未下载完成")

    def remove_task(self, task_id: str):
        self._tasks.pop(task_id, None)
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0) and self.table.item(row, 0).data(Qt.UserRole) == task_id:
                self.table.removeRow(row)
                break
        self._update_empty_state()

    def update_task(self, task_id: str, **kwargs):
        info = self._tasks.get(task_id)
        if not info:
            return
        for key, value in kwargs.items():
            if hasattr(info, key):
                setattr(info, key, value)
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0) and self.table.item(row, 0).data(Qt.UserRole) == task_id:
                self.table.item(row, 1).setText(format_size(info.total_size))
                self.table.item(row, 2).setText(format_size(info.speed) + "/s" if info.speed > 0 else "--")
                bar = self.table.cellWidget(row, 3)
                if isinstance(bar, QProgressBar):
                    bar.setValue(int(info.progress))
                self.table.item(row, 4).setText(format_eta(info.eta))
                self.table.item(row, 5).setText(info.status)
                self.table.item(row, 5).setForeground(QColor(STATUS_COLORS.get(info.status, "#d7d8db")))
                break

    def get_task(self, task_id: str) -> TaskInfo | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[TaskInfo]:
        return list(self._tasks.values())

    def task_count(self) -> int:
        return len(self._tasks)

    def current_total_speed(self) -> float:
        return sum(t.speed for t in self._tasks.values() if t.status == "下载中")

    def _update_empty_state(self):
        empty = self.table.rowCount() == 0
        self.empty_label.setVisible(empty)
        self.label_empty_hint.setVisible(empty)

    # ---------- 新建任务入口 ----------
    def prompt_new_task_with(self, url: str, name: str = ""):
        """带预填地址的新建任务(历史重新下载)."""
        from app.ui.parse_dialog import ParseResultDialog

        parse_dialog = ParseResultDialog(url, name, self, default_name=name)
        if parse_dialog.exec() != QDialog.Accepted or not parse_dialog.task_info:
            return
        info = parse_dialog.task_info
        self.add_task(info)
        self.task_created.emit(info)

    def prompt_new_task(self):
        from app.ui.parse_dialog import ParseResultDialog

        dialog = NewTaskDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        source = dialog.input_url.text().strip() or dialog.input_file.text().strip()
        preset_name = dialog.input_name.text().strip()
        auto_convert = dialog.auto_convert
        parse_dialog = ParseResultDialog(source, preset_name, self, default_name=preset_name)
        if parse_dialog.exec() != QDialog.Accepted or not parse_dialog.task_info:
            return
        info = parse_dialog.task_info
        info.auto_convert = auto_convert
        self.add_task(info)
        self.task_created.emit(info)

    def prompt_batch_add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "批量选择M3U8文件", "", "M3U8文件 (*.m3u8);;所有文件 (*)")
        if not paths:
            return
        added, failed = 0, []
        for path in paths:
            try:
                from app.core.m3u8_parser import parse_m3u8

                parsed = parse_m3u8(path)
                name = sanitize_filename(parsed.title or os.path.splitext(os.path.basename(path))[0])
                info = TaskInfo(
                    name=name,
                    url=path,
                    duration=parsed.duration,
                    resolution=parsed.resolution,
                    segment_count=parsed.segment_count,
                    segment_type=parsed.segment_type,
                    encrypted=parsed.encrypted,
                    key_method=parsed.key_method,
                    key_url=parsed.key_url,
                )
            except Exception as exc:
                failed.append(f"{os.path.basename(path)}: {exc}")
                continue
            self.add_task(info)
            self.task_created.emit(info)
            added += 1
        logger.info("批量添加 %s 个任务, 失败 %s 个", added, len(failed))
        if failed:
            QMessageBox.warning(self, "批量添加", f"成功 {added} 个, 失败 {len(failed)} 个:\n" + "\n".join(failed[:8]))
        else:
            QMessageBox.information(self, "批量添加", f"已添加 {added} 个任务")
