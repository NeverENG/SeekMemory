"""Own the SQLite connection and delegate unchanged migrations; retain existing time helpers.

管理 SQLite 连接并委托既有迁移，保留现有时间帮助函数。
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

try:
    from .serialization import dump_json, load_json_any, load_json_object, pick_dataclass_fields
    from .migrations import migrate
except ImportError:  # Existing standalone mode / 保留已有的独立导入方式。
    from serialization import dump_json, load_json_any, load_json_object, pick_dataclass_fields
    from migrations import migrate

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    """Read the existing local ISO timestamp / 读取既有的本地 ISO 时间戳。"""
    return datetime.datetime.now().isoformat(timespec="seconds")


def parse_time(value: str) -> datetime.datetime | None:
    """Parse the stored ISO value without timezone conversion; invalid values return None / 解析已存 ISO 值，不转换时区，无效值返回空。"""
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def age_seconds(value: datetime.datetime | None, now: datetime.datetime) -> float:
    """Read elapsed seconds with existing timestamp semantics and a zero fallback / 按既有时间戳语义计算经过秒数，失败回退为零。"""
    if value is None:
        return 0.0
    try:
        return max(0.0, now.timestamp() - value.timestamp())
    except (OSError, OverflowError, ValueError):
        return 0.0


class SqliteDatabase:
    """Own connection setup, compatible schema initialization and shutdown / 管理连接建立、兼容的结构初始化及关闭。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate()

    def _migrate(self) -> None:
        """Delegate the existing ordered migration steps / 委托执行既有的有序迁移步骤。"""
        migrate(self.conn)

    def close(self) -> None:
        """Close the owned SQLite connection / 关闭自有 SQLite 连接。"""
        self.conn.close()


class SqliteRepository:
    """Borrow a database connection; public write operations own their transactions / 借用数据库连接，由公开写入操作负责事务。"""

    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    @property
    def conn(self) -> sqlite3.Connection:
        """Borrow the shared SQLite connection; do not close it from a repository / 借用共享 SQLite 连接，仓储不能将其关闭。"""
        return self.db.conn
