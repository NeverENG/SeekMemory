"""SQLite store composition.

One database file and one connection are intentional so Artifact commits,
Source admission and ledger writes remain atomic.
"""

from __future__ import annotations

try:
    from .artifacts import ArtifactRepository
    from .dreams import DreamRepository
    from .extraction import ExtractionRepository
    from .imports import HistoryImportRepository
    from .ledger import LedgerRepository
    from .metrics import StoreMetricsRepository
    from .runtime_episodes import RuntimeEpisodeRepository
    from .runtime_state import RuntimeStateRepository
    from .sources import SourceRepository
    from .sqlite import SqliteDatabase
except ImportError:  # standalone imports from the store directory
    from artifacts import ArtifactRepository
    from dreams import DreamRepository
    from extraction import ExtractionRepository
    from imports import HistoryImportRepository
    from ledger import LedgerRepository
    from metrics import StoreMetricsRepository
    from runtime_episodes import RuntimeEpisodeRepository
    from runtime_state import RuntimeStateRepository
    from sources import SourceRepository
    from sqlite import SqliteDatabase


class Store:
    """Repository bundle over one SQLite connection."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.database = SqliteDatabase(path)
        self.artifacts = ArtifactRepository(self.database)
        self.sources = SourceRepository(self.database)
        self.extraction = ExtractionRepository(self.database)
        self.imports = HistoryImportRepository(self.database)
        self.ledger = LedgerRepository(self.database)
        self.runtime_state = RuntimeStateRepository(self.database)
        self.runtime_episodes = RuntimeEpisodeRepository(self.database)
        self.dreams = DreamRepository(self.database)
        self.metrics = StoreMetricsRepository(self.database, self.extraction)

    @property
    def conn(self):
        return self.database.conn

    def close(self) -> None:
        self.database.close()


def open_store(path: str) -> Store:
    """Open one store repository bundle."""
    return Store(path)


__all__ = ["Store", "open_store"]
