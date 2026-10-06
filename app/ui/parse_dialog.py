"""任务创建前的解析结果展示与确认对话框."""

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.core.m3u8_parser import (
    DRMProtectedError,
    M3U8Info,
    ParseError,
    get_audio_info,
    parse_m3u8,
)
from app.ui.task_widget import TaskInfo, sanitize_filename

logger = logging.getLogger("m3u8ToMp4.parse_dialog")


class ParseWorker(QThread):
    """后台解析线程, 避免 UI 卡顿."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, source: str, title: str = "", parent=None):
        super().__init__(parent)
        self.source = source
        self.title = title

    def run(self):
        try:
            info = parse_m3u8(self.source, self.title)
            self.finished_ok.emit(info)
        except DRMProtectedError as exc:
            self.failed.emit(str(exc))
        except ParseError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            logger.exception("解析异常")
            self.failed.emit(f"解析异常: {exc}")


class ParseResultDialog(QDialog):
    """展示解析结果, 用户确认后创建任务."""

    def __init__(self, source: str, title: str = "", parent=None, default_name: str = ""):
        super().__init__(parent)
        self.setWindowTitle("解析视频信息")
        self.setMinimumWidth(560)
        self.parsed_info: M3U8Info | None = None
        self.task_info: TaskInfo | None = None
        self._source = source
        self._title = title
        self._build_ui(default_name)
        self._start_parse()

    def _build_ui(self, default_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        self.label_status = QLabel("正在解析 M3U8 ...")
        self.label_status.setStyleSheet("color: #f59e0b; font-size: 14px; font-weight: bold;")
        layout.addWidget(self.label_status)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        layout.addWidget(self.progress)

        group = QGroupBox("视频信息")
        form = QFormLayout(group)
        form.setSpacing(8)
        self.val_name = QLabel("--")
        self.val_resolution = QLabel("--")
        self.val_bandwidth = QLabel("--")
        self.val_duration = QLabel("--")
        self.val_codec = QLabel("--")
        self.val_audio = QLabel("--")
        self.val_segments = QLabel("--")
        self.val_type = QLabel("--")
        self.val_encrypt = QLabel("--")
        for key, widget in (
            ("名称:", self.val_name),
            ("分辨率:", self.val_resolution),
            ("码率:", self.val_bandwidth),
            ("时长:", self.val_duration),
            ("编码:", self.val_codec),
            ("音频:", self.val_audio),
            ("分片数:", self.val_segments),
            ("分片类型:", self.val_type),
            ("加密:", self.val_encrypt),
        ):
            form.addRow(key, widget)
        self._info_group = group
        self._info_group.setVisible(False)
        layout.addWidget(self._info_group)

        name_group = QGroupBox("任务设置")
        name_form = QFormLayout(name_group)
        self.edit_name = QLineEdit(default_name)
        self.edit_name.setPlaceholderText("自动命名(去除非法字符)")
        name_form.addRow("视频名称:", self.edit_name)

        seg_row = QHBoxLayout()
        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 16)
        self.spin_threads.setValue(5)
        self.label_hint = QLabel("并发下载分片线程数")
        self.label_hint.setStyleSheet("color: #8a8f98;")
        seg_row.addWidget(self.spin_threads)
        seg_row.addWidget(self.label_hint, 1)
        name_form.addRow("下载线程:", seg_row)
        self._name_group = name_group
        self._name_group.setVisible(False)
        layout.addWidget(self._name_group)

        self.label_error = QLabel("")
        self.label_error.setWordWrap(True)
        self.label_error.setStyleSheet("color: #ef4444; font-size: 13px;")
        self.label_error.setVisible(False)
        layout.addWidget(self.label_error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btn_ok = buttons.button(QDialogButtonBox.Ok)
        self.btn_ok.setText("创建任务")
        self.btn_ok.setObjectName("primaryButton")
        self.btn_ok.setEnabled(False)
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._buttons = buttons

    def _start_parse(self):
        self._worker = ParseWorker(self._source, self._title, self)
        self._worker.finished_ok.connect(self._on_parsed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_parsed(self, info: M3U8Info):
        self.parsed_info = info
        self.progress.setVisible(False)
        self.label_status.setText("解析成功")
        self.label_status.setStyleSheet("color: #22c55e; font-size: 14px; font-weight: bold;")
        self.val_name.setText(info.title)
        self.val_resolution.setText(info.resolution_label)
        self.val_bandwidth.setText(info.bandwidth_label)
        self.val_duration.setText(info.duration_label)
        self.val_codec.setText(info.codecs or "未知")
        self.val_audio.setText(get_audio_info(info))
        self.val_segments.setText(f"{info.segment_count} 个")
        self.val_type.setText(info.type_label)
        if info.encrypted:
            self.val_encrypt.setText(f"是 ({info.key_method}, 普通密钥可解析)")
            self.val_encrypt.setStyleSheet("color: #f59e0b;")
        else:
            self.val_encrypt.setText("否")
            self.val_encrypt.setStyleSheet("color: #22c55e;")
        self._info_group.setVisible(True)
        self._name_group.setVisible(True)
        if not self.edit_name.text().strip():
            self.edit_name.setText(sanitize_filename(info.title))
        self.btn_ok.setEnabled(True)

    def _on_failed(self, message: str):
        self.progress.setVisible(False)
        self.label_status.setText("解析失败")
        self.label_status.setStyleSheet("color: #ef4444; font-size: 14px; font-weight: bold;")
        self.label_error.setText(message)
        self.label_error.setVisible(True)
        self.btn_ok.setEnabled(False)
        if "DRM" in message:
            QMessageBox.warning(self, "DRM 保护", message)

    def _accept(self):
        if not self.parsed_info:
            return
        name = sanitize_filename(self.edit_name.text().strip() or self.parsed_info.title)
        info = self.parsed_info
        self.task_info = TaskInfo(
            name=name,
            url=self._source,
            status="等待",
            total_size=-1,
            file_path="",
            duration=info.duration,
            resolution=info.resolution,
            segment_count=info.segment_count,
            segment_type=info.segment_type,
            encrypted=info.encrypted,
            key_method=info.key_method,
            key_url=info.key_url,
            threads=self.spin_threads.value(),
        )
        if info.segments:
            from urllib.parse import urlparse
            p = urlparse(info.segments[0].uri)
            if p.scheme and p.netloc:
                self.task_info.referer = f"{p.scheme}://{p.netloc}/"
        self.accept()

    @property
    def thread_count(self) -> int:
        return self.spin_threads.value()

    @property
    def m3u8_info(self) -> M3U8Info | None:
        return self.parsed_info
