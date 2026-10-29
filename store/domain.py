"""Explicit persistence capabilities; exports only, without SQL implementation.

明确持久化对外能力，仅导出，不实现 SQL；资源生命周期见 composition。
"""
from .composition import Store, open_store
from .artifacts import ArtifactRepository
from .sources import SourceRepository
from .extraction import ExtractionRepository
from .ledger import Ledger, LedgerRepository, chain_hash, chain_payload
from .runtime_state import RuntimeStateRepository
from .runtime_episodes import RuntimeEpisodeRepository
from .dreams import DreamRepository
from .metrics import StoreMetricsRepository
from .cache import Cache
from .run_trace import TraceStore

__all__ = [
    "Store", "open_store", "ArtifactRepository", "SourceRepository", "ExtractionRepository",
    "Ledger", "LedgerRepository", "chain_hash", "chain_payload", "RuntimeStateRepository",
    "RuntimeEpisodeRepository", "DreamRepository", "StoreMetricsRepository", "Cache", "TraceStore",
]
