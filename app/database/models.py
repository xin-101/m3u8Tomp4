from dataclasses import dataclass, field


@dataclass
class DownloadTask:
    """download_task 表模型"""

    id: int | None = None
    url: str = ""
    name: str = ""
    status: str = "等待"
    progress: float = 0.0
    download_path: str = ""
    created_time: str = ""


@dataclass
class HistoryRecord:
    """history 表模型(Phase 6)"""

    id: int | None = None
    file_name: str = ""
    size: int = 0
    download_path: str = ""
    status: str = "完成"
    created_time: str = ""
