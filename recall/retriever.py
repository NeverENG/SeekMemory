"""Combine graph activation and optional BM25 over supplied candidates; own derived index only.

在给定候选中组合图激活及可选 BM25，仅管理派生索引。
"""
from __future__ import annotations

from dataclasses import replace

try:
    from ..app.ports import ArtifactCache
    from ..core.artifact import Artifact
    from ..core.graph import Graph
    from ..core.retrieval import RetrievalCandidate
    from .bm25 import BM25Index
    from .seed import seeds
    from .spread import activate
except ImportError:
    from app.ports import ArtifactCache
    from core.artifact import Artifact
    from core.graph import Graph
    from core.retrieval import RetrievalCandidate
    from recall.bm25 import BM25Index
    from recall.seed import seeds
    from recall.spread import activate


class GraphRetriever:
    """Read graph activation for supplied candidates / 为给定候选读取图激活。"""
    def __init__(self, graph: Graph, cache: ArtifactCache) -> None:
        self.graph = graph
        self.cache = cache

    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]:
        """Return graph and lexical evidence for supplied candidates without writes / 为给定候选返回图及字面证据，不执行写入。"""
        seed_ids = seeds(query, pool)
        activation = activate(seed_ids, self.graph, self.cache)
        return [RetrievalCandidate(art, float(activation.get(art.header.id, 0.0)))
                for art in pool]


class HybridRetriever:
    """Combine graph and pool-local BM25; rebuild when cache version changes / 组合图及池内 BM25，缓存版本变化时重建。"""

    def __init__(self, graph: Graph, cache: ArtifactCache,
                 index: BM25Index | None = None) -> None:
        self.graph = graph
        self.cache = cache
        self.index = index or BM25Index()
        self._indexed_version = -1

    def _ensure_index(self) -> None:
        """Refresh the derived lexical index only when its cache snapshot changed / 仅在缓存快照变化时刷新派生字面索引。"""
        version = self.cache.version
        if version != self._indexed_version:
            self.index.rebuild(self.cache.active())
            self._indexed_version = version

    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]:
        """Return graph and lexical evidence for supplied candidates without writes / 为给定候选返回图及字面证据，不执行写入。"""
        self._ensure_index()
        candidates = GraphRetriever(self.graph, self.cache).retrieve(query, pool)
        lexical = self.index.search(query, pool)
        unique: dict[str, RetrievalCandidate] = {}
        for candidate in candidates:
            artifact_id = candidate.artifact.header.id
            current = unique.get(artifact_id)
            if current is None or candidate.activation > current.activation:
                unique[artifact_id] = replace(
                    candidate,
                    lexical=lexical.get(artifact_id, 0.0),
                )
        return list(unique.values())
