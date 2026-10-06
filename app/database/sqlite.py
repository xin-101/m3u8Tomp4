"""SQLite 数据层: 任务持久化(断点恢复) + 历史记录."""

import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("m3u8ToMp4.database")

DEFAULT_DB = os.path.join("logs", "m3u8ToMp4.db")


def _default_db_path() -> str:
    import sys

    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return os.path.join(os.path.dirname(sys.executable), "logs", "m3u8ToMp4.db")
    return DEFAULT_DB

SCHEMA = """
CREATE TABLE IF NOT EXISTS download_task (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    size REAL NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT '等待',
    progress REAL NOT NULL DEFAULT 0,
    segment_count INTEGER NOT NULL DEFAULT 0,
    resolution TEXT NOT NULL DEFAULT '',
    referer TEXT NOT NULL DEFAULT '',
    auto_convert INTEGER NOT NULL DEFAULT 1,
    output_format TEXT NOT NULL DEFAULT 'mp4',
    threads INTEGER NOT NULL DEFAULT 5,
    error TEXT NOT NULL DEFAULT '',
    created_time TEXT NOT NULL DEFAULT '',
    completed_time TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    size REAL NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    download_path TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '完成',
    created_time TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_history_time ON history(created_time DESC);
CREATE INDEX IF NOT EXISTS idx_task_status ON download_task(status);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    """线程安全的 SQLite 访问层(每线程独立连接)."""

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            db_path = _default_db_path()
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=15)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=15000")
            self._local.conn = conn
        return conn

    def _ensure_schema(self):
        with self._init_lock:
            if self._initialized:
                return
            try:
                conn = self._conn()
                conn.executescript(SCHEMA)
                conn.commit()
                self._initialized = True
                logger.info("数据库就绪: %s", self.db_path)
            except sqlite3.Error as exc:
                logger.error("数据库初始化失败: %s", exc)
                raise

    def close(self):
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    # ---------- 任务表(断点恢复) ----------
    def upsert_task(self, task: dict):
        """保存/更新任务(用于关闭时持久化与进度同步)."""
        fields = ["id", "url", "name", "path", "size", "duration", "status",
                  "progress", "segment_count", "resolution", "referer",
                  "auto_convert", "output_format", "threads", "error",
                  "created_time", "completed_time"]
        data = {k: task.get(k, "") if k in ("id", "url", "name", "path", "status",
                                            "resolution", "referer", "output_format",
                                            "error", "created_time", "completed_time")
                else task.get(k, 0) for k in fields}
        if not data["created_time"]:
            data["created_time"] = _now()
        placeholders = ", ".join("?" for _ in fields)
        columns = ", ".join(fields)
        updates = ", ".join(f"{k}=excluded.{k}" for k in fields if k != "id")
        try:
            conn = self._conn()
            conn.execute(
                f"INSERT INTO download_task ({columns}) VALUES ({placeholders}) "
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                tuple(data[k] for k in fields),
            )
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("upsert_task 失败: %s", exc)

    def update_task_status(self, task_id: str, status: str, progress: float | None = None,
                           path: str = "", error: str = ""):
        try:
            conn = self._conn()
            sets = ["status=?"]
            params: list = [status]
            if progress is not None:
                sets.append("progress=?")
                params.append(progress)
            if path:
                sets.append("path=?")
                params.append(path)
            if error:
                sets.append("error=?")
                params.append(error)
            if status == "完成":
                sets.append("completed_time=?")
                params.append(_now())
            params.append(task_id)
            conn.execute(f"UPDATE download_task SET {', '.join(sets)} WHERE id=?", params)
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("update_task_status 失败: %s", exc)

    def get_unfinished_tasks(self) -> list[dict]:
        """获取未完成任务(用于启动恢复)."""
        try:
            conn = self._conn()
            rows = conn.execute(
                "SELECT * FROM download_task WHERE status NOT IN ('完成') ORDER BY created_time"
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.warning("get_unfinished_tasks 失败: %s", exc)
            return []

    def delete_task(self, task_id: str):
        try:
            conn = self._conn()
            conn.execute("DELETE FROM download_task WHERE id=?", (task_id,))
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("delete_task 失败: %s", exc)

    def clear_finished_tasks(self):
        try:
            conn = self._conn()
            conn.execute("DELETE FROM download_task WHERE status='完成'")
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("clear_finished_tasks 失败: %s", exc)

    # ---------- 历史表 ----------
    def add_history(self, file_name: str, size: float, download_path: str,
                    source_url: str = "", duration: float = 0.0,
                    status: str = "完成", task_id: str = "") -> int:
        try:
            conn = self._conn()
            cur = conn.execute(
                "INSERT INTO history (task_id, file_name, size, duration, download_path, "
                "source_url, status, created_time) VALUES (?,?,?,?,?,?,?,?)",
                (task_id, file_name, size, duration, download_path, source_url, status, _now()),
            )
            conn.commit()
            return int(cur.lastrowid or 0)
        except sqlite3.Error as exc:
            logger.warning("add_history 失败: %s", exc)
            return 0

    def get_history(self, keyword: str = "", limit: int = 500) -> list[dict]:
        try:
            conn = self._conn()
            if keyword:
                like = f"%{keyword}%"
                rows = conn.execute(
                    "SELECT * FROM history WHERE file_name LIKE ? OR source_url LIKE ? "
                    "ORDER BY id DESC LIMIT ?", (like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            logger.warning("get_history 失败: %s", exc)
            return []

    def delete_history(self, history_id: int):
        try:
            conn = self._conn()
            conn.execute("DELETE FROM history WHERE id=?", (history_id,))
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("delete_history 失败: %s", exc)

    def clear_history(self):
        try:
            conn = self._conn()
            conn.execute("DELETE FROM history")
            conn.commit()
        except sqlite3.Error as exc:
            logger.warning("clear_history 失败: %s", exc)

    def search_history(self, keyword: str) -> list[dict]:
        return self.get_history(keyword)
