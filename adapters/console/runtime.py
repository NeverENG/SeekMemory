"""Compose the management use cases without starting a chat host or workers."""

from __future__ import annotations

from pathlib import Path

from ...app.budget import ContextBudget
from ...app.config import Settings
from ...core.graph import Graph
from ...recall.retriever import HybridRetriever
from ...services.management_service import ManagementService
from ...services.recall_service import RecallService
from ...services.status_service import StatusService
from ...store import open_store
from ...store.cache import Cache
from ...store.run_trace import TraceStore
from ..persona_packs import FilePersonaPacks


class ConsoleRuntime:
    """Own one local database; do not share its active cache with another process."""

    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings()
        self.store = open_store(str(data_dir / "memory.db"))
        try:
            cache = Cache(self.store.artifacts)
            cache.load()
            graph = Graph(self.store.artifacts)
            recall = RecallService(
                cache=cache, graph=graph, artifacts=self.store.artifacts,
                sources=self.store.sources, budget=ContextBudget(),
                config=self.settings.get, owner_umo=lambda: "",
                hybrid_retriever=HybridRetriever(graph, cache),
            )
            self.management = ManagementService(
                self.store.artifacts, self.store.sources, self.store.ledger,
                cache, recall,
                packs=FilePersonaPacks(
                    Path(__file__).resolve().parents[2] / "persona_seeds",
                    data_dir / "persona_packs",
                ),
                dreams=self.store.dreams,
            )
            self.status_service = StatusService(
                artifacts=self.store.artifacts, ledger=self.store.ledger,
            )
            self.traces = TraceStore(data_dir / "run_traces.jsonl", read_only=True)
        except BaseException:
            self.store.close()
            raise

    def status(self) -> dict:
        """Report actual console capabilities; no provider or scheduler is started."""
        return {
            "ready": True,
            "checks": [
                {"name": "engine", "ok": True, "detail": "独立控制台已连接"},
                {"name": "ledger", "ok": self.status_service.ledger_valid(),
                 "detail": "账本哈希链"},
            ],
            "activeTask": None,
            "pending": [],
            "pendingTopics": [],
            "extractionPolicy": {"backlogThreshold": 30, "topicTtlSeconds": 86400,
                                 "maxTopicsPerBatch": 6},
            "capacity": None,
            "persona": self.status_service.persona(),
            "checkpointPending": None,
            "schedulerCount": 0,
            "config": {},
            "capabilities": {"maintenanceTasks": False},
        }

    def close(self) -> None:
        """Release the database connection owned by this process."""
        self.store.close()
