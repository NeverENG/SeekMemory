"""Construct repositories over one owned SQLite connection; repository operations own transactions.

在一个自有 SQLite 连接上组装仓储，各仓储操作管理事务。
"""

from __future__ import annotations

import sqlite3

try:
    from .artifacts import ArtifactRepository
    from .dreams import DreamRepository
    from .extraction import ExtractionRepository
    from .ledger import LedgerRepository
    from .metrics import StoreMetricsRepository
    from .runtime_episodes import RuntimeEpisodeRepository
    from .runtime_state import RuntimeStateRepository
    from .sources import SourceRepository
    from .sqlite import SqliteDatabase
except ImportError:  # Existing standalone mode / 保留已有的独立导入方式。
    from artifacts import ArtifactRepository
    from dreams import DreamRepository
    from extraction import ExtractionRepository
    from ledger import LedgerRepository
    from metrics import StoreMetricsRepository
    from runtime_episodes import RuntimeEpisodeRepository
    from runtime_state import RuntimeStateRepository
    from sources import SourceRepository
    from sqlite import SqliteDatabase


class Store:
    """Own one connection and its repository bundle / 管理一个连接及其仓储集合。"""

    def __init__(self, path: str) -> None:
        self.path = path
        self.database = SqliteDatabase(path)
        self.artifacts = ArtifactRepository(self.database)
        self.sources = SourceRepository(self.database)
        self.extraction = ExtractionRepository(self.database)
        self.ledger = LedgerRepository(self.database)
        self.runtime_state = RuntimeStateRepository(self.database)
        self.runtime_episodes = RuntimeEpisodeRepository(self.database)
        self.dreams = DreamRepository(self.database)
        self.metrics = StoreMetricsRepository(self.database, self.extraction)

    @property
    def conn(self) -> sqlite3.Connection:
        """Borrow the shared SQLite connection; do not close it from a repository / 借用共享 SQLite 连接，仓储不能将其关闭。"""
        return self.database.conn

    def close(self) -> None:
        """Close the owned SQLite connection / 关闭自有 SQLite 连接。"""
        self.database.close()


def open_store(path: str) -> Store:
    """Create a repository bundle; the caller must close it / 创建仓储集合，由调用方负责关闭。"""
    return Store(path)


__all__ = ["Store", "open_store"]
