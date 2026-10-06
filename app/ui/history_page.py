"""历史记录页面: 搜索、删除、打开目录、重新下载."""

import logging
import os
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("m3u8ToMp4.history")


def _format_size(size_bytes: float) -> str:
    if not size_bytes or size_bytes < 0:
        return "--"
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    value = float(size_bytes)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    return f"{value:.2f} {units[idx]}"


class HistoryPage(QWidget):
    redownload_requested = Signal(str, str)  # url, name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._records: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("历史记录")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #ffffff;")
        header.addWidget(title)
        header.addStretch(1)

        self.edit_search = QLineEdit()
        self.edit_search.setPlaceholderText("搜索文件名 / 链接...")
        self.edit_search.setFixedWidth(260)
        self.edit_search.returnPressed.connect(self._search)
        self.edit_search.textChanged.connect(self._filter)
        header.addWidget(self.edit_search)

        for text, slot in (
            ("刷新", self.refresh),
            ("重新下载", self._redownload),
            ("打开目录", self._open_dir),
            ("删除记录", self._delete_selected),
            ("清空历史", self._clear_all),
        ):
            btn = QPushButton(text)
            btn.setObjectName("actionButton")
            btn.clicked.connect(slot)
            header.addWidget(btn)
        layout.addLayout(header)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["ID", "文件名", "大小", "时间", "路径", "状态"])
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setColumnHidden(0, True)
        self.table.itemDoubleClicked.connect(lambda *_: self._open_dir())
        hv = self.table.horizontalHeader()
        hv.setSectionResizeMode(1, QHeaderView.Stretch)
        hv.setSectionResizeMode(4, QHeaderView.Stretch)
        for col in (2, 3, 5):
            hv.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        self.hint = QLabel("暂无历史记录, 完成的任务会自动出现在这里")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setStyleSheet("color: #55585f; font-size: 14px;")
        layout.addWidget(self.hint, 1)

    # ---------- 数据 ----------
    def refresh(self, keyword: str = ""):
        try:
            from app.database.sqlite import Database

            db = Database()
            self._records = db.get_history(keyword)
        except Exception as exc:
            logger.warning("历史记录加载失败: %s", exc)
            self._records = []
        self._populate(self._records)

    def _populate(self, records: list[dict]):
        self.table.setRowCount(0)
        for rec in records:
            row = self.table.rowCount()
            self.table.insertRow(row)
            id_item = QTableWidgetItem(str(rec.get("id", "")))
            self.table.setItem(row, 0, id_item)
            self.table.setItem(row, 1, QTableWidgetItem(rec.get("file_name", "")))
            self.table.setItem(row, 2, QTableWidgetItem(_format_size(rec.get("size", 0))))
            self.table.setItem(row, 3, QTableWidgetItem(rec.get("created_time", "")))
            self.table.setItem(row, 4, QTableWidgetItem(rec.get("download_path", "")))
            self.table.setItem(row, 5, QTableWidgetItem(rec.get("status", "")))
        self.hint.setVisible(self.table.rowCount() == 0)

    def _search(self):
        self.refresh(self.edit_search.text().strip())

    def _filter(self, text: str):
        text = text.lower().strip()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            url_item = None
            haystack = (name_item.text() if name_item else "")
            match = text in haystack.lower()
            self.table.setRowHidden(row, not match)

    def _selected_record(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "提示", "请先选择一条记录")
            return None
        id_item = self.table.item(row, 0)
        if not id_item:
            return None
        rec_id = int(id_item.text())
        for rec in self._records:
            if int(rec.get("id", 0)) == rec_id:
                return rec
        return None

    # ---------- 操作 ----------
    def _redownload(self):
        rec = self._selected_record()
        if not rec:
            return
        url = rec.get("source_url", "")
        if not url:
            QMessageBox.information(self, "提示", "该记录没有源链接")
            return
        self.redownload_requested.emit(url, rec.get("file_name", ""))
        logger.info("重新下载: %s", url)

    def _open_dir(self):
        rec = self._selected_record()
        if not rec:
            return
        path = rec.get("download_path", "")
        if path and os.path.exists(path):
            target = path if os.path.isdir(path) else os.path.dirname(path)
            if os.name == "nt":
                if os.path.isfile(path):
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                else:
                    os.startfile(target)
            else:
                subprocess.Popen(["xdg-open", target])
        else:
            QMessageBox.information(self, "提示", "文件不存在(可能已被移动或删除)")

    def _delete_selected(self):
        rec = self._selected_record()
        if not rec:
            return
        ret = QMessageBox.question(self, "删除记录", f"删除历史记录「{rec.get('file_name', '')}」?\n(不会删除本地文件)")
        if ret != QMessageBox.Yes:
            return
        try:
            from app.database.sqlite import Database

            Database().delete_history(int(rec["id"]))
            self.refresh(self.edit_search.text().strip())
            logger.info("历史记录已删除: %s", rec.get("file_name"))
        except Exception as exc:
            QMessageBox.warning(self, "删除失败", str(exc))

    def _clear_all(self):
        if self.table.rowCount() == 0:
            return
        ret = QMessageBox.question(self, "清空历史", "确定清空全部历史记录?\n(不会删除本地文件)")
        if ret != QMessageBox.Yes:
            return
        try:
            from app.database.sqlite import Database

            Database().clear_history()
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "清空失败", str(exc))
