"""Coordinate recall and its compatible designated-context writeback behavior.

协调召回及兼容的指定记忆上下文写回行为，资源由调用方管理。
"""

from __future__ import annotations

from typing import Any, Callable

try:
    from .ports import ArtifactCache, ArtifactStore, SourceStore
    from ..core.graph import Graph
    from ..app.budget import ContextBudget
    from ..app.cache_repair import CacheRepairs
except ImportError:
    from services.ports import ArtifactCache, ArtifactStore, SourceStore
    from core.graph import Graph
    from app.budget import ContextBudget
    from app.cache_repair import CacheRepairs

try:
    from ..recall.designated import deliverable
    from ..recall.pipeline import query_block
    from ..recall.context_recording import record_context, ContextRecorder
    from ..recall.scope import visible
except ImportError:
    from recall.designated import deliverable
    from recall.pipeline import query_block
    from recall.context_recording import record_context, ContextRecorder
    from recall.scope import visible


class RecallService:
    """Coordinate recall inputs and budgets; callers own stores and retrievers / 协调召回输入与预算，仓储和检索器由调用方管理。"""

    def __init__(
        self,
        *,
        cache: ArtifactCache | None,
        graph: Graph | None,
        artifacts: ArtifactStore | None,
        sources: SourceStore | None,
        budget: ContextBudget,
        config: Callable[[str, Any], Any],
        owner_umo: Callable[[], str],
        hybrid_retriever=None,
        log: Callable[[str], None] | None = None,
        cache_repairs: CacheRepairs | None = None,
    ) -> None:
        self.cache = cache
        self.graph = graph
        self.artifacts = artifacts
        self.sources = sources
        self.budget = budget
        self.config = config
        self.owner_umo = owner_umo
        self.hybrid_retriever = hybrid_retriever
        self.log = log or (lambda _msg: None)
        self._context_writer = ContextRecorder(artifacts, cache, cache_repairs=cache_repairs)

    def query(
        self,
        text: str,
        session_id: str = "",
        private: bool = False,
        speaker: str = "",
        *,
        degraded: bool = False,
    ) -> tuple[str, dict]:
        """Query disclosed context without any memory writes / 查询已披露上下文，不写入任何记忆。"""
        budget_chars = int(self.budget.injection_chars)
        recall_k = int(self.config("recall_k", 8))
        if degraded:
            budget_chars = max(80, budget_chars // 2)
            recall_k = max(1, recall_k // 2)

        source_fields = {
            "source_recall_enabled",
            "source_recall_hours",
            "source_recall_max_candidates",
        }

        def conf(key: str, default):
            if key == "budget_chars":
                return budget_chars
            if key == "recall_k":
                return recall_k
            if key in source_fields:
                value = getattr(self.budget, key, None)
                return self.config(key, default) if value is None else value
            return self.config(key, default)

        return query_block(
            self.cache,
            self.graph,
            self.artifacts,
            self.sources,
            session_id,
            text,
            private,
            conf,
            self.owner_umo(),
            speaker,
            log=self.log,
            hybrid_retriever=self.hybrid_retriever,
        )

    def build(
        self, text: str, session_id: str = "", private: bool = False, speaker: str = "",
        *, degraded: bool = False, dry_run: bool = False,
    ) -> tuple[str, dict]:
        """Keep compatible query-plus-recording behavior; dry_run is read-only.

        保留兼容的查询加记录行为，dry_run 只读；新调用方应明确选择 query 与注入记录。
        """
        block, info = self.query(text, session_id, private, speaker, degraded=degraded)
        if not dry_run:
            self.record_context_injection(block, info)
        return block, info

    def record_context_injection(self, block: str, info: dict) -> int:
        """Record actual model-context inclusion, before any model/send outcome.

        在模型或发送产生结果之前记录实际进入模型上下文的内容；预览不调用本入口。
        """
        return self._context_writer.record(block, info)

    def retry_writebacks(self) -> int:
        """Resume inclusion commits/cache repairs without recall or model calls.

        恢复包含记录提交及缓存补偿，不进行召回或模型调用。
        """
        return self._context_writer.retry_writebacks()

    def preview(self, text: str, session_id: str, private: bool,
                speaker: str = "") -> dict:
        """Preview recall without writing designated delivery state / 预览召回，不写入指定记忆的交付状态。"""
        block, info = self.query(text, session_id, private, speaker)
        owner = self.owner_umo()
        pool = self.cache.active() if self.cache is not None else []
        eligible = visible(pool, session_id, owner, self.sources.source_umo)
        eligible = [
            art for art in eligible if deliverable(art, text, private)
        ]
        ids = {art.header.id for art in eligible}
        return {
            "block": block,
            "info": info,
            "visible": sorted(ids),
            "excluded": [art.header.id for art in pool if art.header.id not in ids],
        }
