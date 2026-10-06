import logging
import os

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

logger = logging.getLogger("m3u8ToMp4.settings")

SPEED_OPTIONS = [
    ("不限速", 0),
    ("500 KB/s", 500 * 1024),
    ("1 MB/s", 1024 * 1024),
    ("5 MB/s", 5 * 1024 * 1024),
    ("10 MB/s", 10 * 1024 * 1024),
]


class AppConfig:
    """应用配置(基于 QSettings 持久化)"""

    def __init__(self):
        self._settings = QSettings("m3u8ToMp4", "m3u8ToMp4")

    @property
    def download_dir(self) -> str:
        default = os.path.join(os.path.expanduser("~"), "Downloads", "m3u8ToMp4")
        return self._settings.value("download_dir", default, type=str)

    @download_dir.setter
    def download_dir(self, value: str):
        self._settings.setValue("download_dir", value)

    @property
    def max_concurrent(self) -> int:
        return int(self._settings.value("max_concurrent", 3, type=int))

    @max_concurrent.setter
    def max_concurrent(self, value: int):
        self._settings.setValue("max_concurrent", value)

    @property
    def speed_limit(self) -> int:
        return int(self._settings.value("speed_limit", 0, type=int))

    @speed_limit.setter
    def speed_limit(self, value: int):
        self._settings.setValue("speed_limit", value)

    @property
    def ffmpeg_path(self) -> str:
        return self._settings.value("ffmpeg_path", "ffmpeg", type=str)

    @ffmpeg_path.setter
    def ffmpeg_path(self, value: str):
        self._settings.setValue("ffmpeg_path", value)

    @property
    def auto_convert(self) -> bool:
        return self._settings.value("auto_convert", True, type=bool)

    @auto_convert.setter
    def auto_convert(self, value: bool):
        self._settings.setValue("auto_convert", value)

    @property
    def auto_start(self) -> bool:
        return self._settings.value("auto_start", False, type=bool)

    @auto_start.setter
    def auto_start(self, value: bool):
        self._settings.setValue("auto_start", value)

    @property
    def output_format(self) -> str:
        return self._settings.value("output_format", "mp4", type=str)

    @output_format.setter
    def output_format(self, value: str):
        self._settings.setValue("output_format", value)


class SettingsDialog(QDialog):
    def __init__(self, parent=None, config: AppConfig | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        self.config = config or AppConfig()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # 下载设置
        group_dl = QGroupBox("下载")
        form_dl = QFormLayout(group_dl)
        form_dl.setSpacing(10)

        dir_row = QHBoxLayout()
        self.edit_download_dir = QLineEdit()
        btn_browse_dir = QPushButton("浏览...")
        btn_browse_dir.setObjectName("actionButton")
        btn_browse_dir.clicked.connect(self._browse_download_dir)
        dir_row.addWidget(self.edit_download_dir, 1)
        dir_row.addWidget(btn_browse_dir)
        form_dl.addRow("下载目录:", dir_row)

        self.spin_concurrent = QSpinBox()
        self.spin_concurrent.setRange(1, 10)
        form_dl.addRow("最大并发任务:", self.spin_concurrent)

        self.combo_speed = QComboBox()
        for label, value in SPEED_OPTIONS:
            self.combo_speed.addItem(label, value)
        form_dl.addRow("下载速度限制:", self.combo_speed)
        layout.addWidget(group_dl)

        # 转换设置
        group_ff = QGroupBox("FFmpeg 转换")
        form_ff = QFormLayout(group_ff)
        form_ff.setSpacing(10)

        ff_row = QHBoxLayout()
        self.edit_ffmpeg = QLineEdit()
        self.edit_ffmpeg.setPlaceholderText("ffmpeg (默认从 PATH 查找)")
        btn_browse_ff = QPushButton("浏览...")
        btn_browse_ff.setObjectName("actionButton")
        btn_browse_ff.clicked.connect(self._browse_ffmpeg)
        ff_row.addWidget(self.edit_ffmpeg, 1)
        ff_row.addWidget(btn_browse_ff)
        form_ff.addRow("FFmpeg 路径:", ff_row)

        self.check_auto_convert = QCheckBox("下载完成后自动转换")
        self.combo_format = QComboBox()
        self.combo_format.addItems(["mp4", "mkv"])
        form_ff.addRow(self.check_auto_convert)
        form_ff.addRow("输出格式:", self.combo_format)
        layout.addWidget(group_ff)

        # 其他
        group_other = QGroupBox("其他")
        form_other = QVBoxLayout(group_other)
        self.check_auto_start = QCheckBox("开机启动")
        form_other.addWidget(self.check_auto_start)
        layout.addWidget(group_other)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.Ok).setObjectName("primaryButton")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_download_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择下载目录", self.edit_download_dir.text())
        if path:
            self.edit_download_dir.setText(path)

    def _browse_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择FFmpeg可执行文件", "", "可执行文件 (*.exe);;所有文件 (*)")
        if path:
            self.edit_ffmpeg.setText(path)

    def _load(self):
        cfg = self.config
        self.edit_download_dir.setText(cfg.download_dir)
        self.spin_concurrent.setValue(cfg.max_concurrent)
        index = self.combo_speed.findData(cfg.speed_limit)
        self.combo_speed.setCurrentIndex(index if index >= 0 else 0)
        self.edit_ffmpeg.setText(cfg.ffmpeg_path)
        self.check_auto_convert.setChecked(cfg.auto_convert)
        self.combo_format.setCurrentText(cfg.output_format)
        self.check_auto_start.setChecked(cfg.auto_start)

    def _save(self):
        cfg = self.config
        cfg.download_dir = self.edit_download_dir.text().strip()
        os.makedirs(cfg.download_dir, exist_ok=True)
        cfg.max_concurrent = self.spin_concurrent.value()
        cfg.speed_limit = int(self.combo_speed.currentData())
        cfg.ffmpeg_path = self.edit_ffmpeg.text().strip() or "ffmpeg"
        cfg.auto_convert = self.check_auto_convert.isChecked()
        cfg.output_format = self.combo_format.currentText()
        cfg.auto_start = self.check_auto_start.isChecked()
        logger.info("设置已保存: dir=%s, concurrent=%s, speed_limit=%s",
                    cfg.download_dir, cfg.max_concurrent, cfg.speed_limit)
        self.accept()
