from __future__ import annotations

from dataclasses import replace

try:
    from ..core.artifact import Artifact
    from ..core.graph import Graph
    from ..core.retrieval import RetrievalCandidate
    from ..store.cache import Cache
    from .bm25 import BM25Index
    from .seed import seeds
    from .spread import activate
except ImportError:
    from core.artifact import Artifact
    from core.graph import Graph
    from core.retrieval import RetrievalCandidate
    from recall.bm25 import BM25Index
    from store.cache import Cache
    from recall.seed import seeds
    from recall.spread import activate


class GraphRetriever:
    def __init__(self, graph: Graph, cache: Cache) -> None:
        self.graph = graph
        self.cache = cache

    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]:
        seed_ids = seeds(query, pool)
        activation = activate(seed_ids, self.graph, self.cache)
        return [RetrievalCandidate(art, float(activation.get(art.header.id, 0.0)))
                for art in pool]


class HybridRetriever:
    """为可见候选池合并图激活和 BM25 词面证据。"""

    def __init__(self, graph: Graph, cache: Cache,
                 index: BM25Index | None = None) -> None:
        self.graph = graph
        self.cache = cache
        self.index = index or BM25Index()
        self._indexed_version = -1

    def _ensure_index(self) -> None:
        version = self.cache.version
        if version != self._indexed_version:
            self.index.rebuild(self.cache.active())
            self._indexed_version = version

    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]:
        """保留图激活，仅按本次 pool 的语料统计附加 BM25 分数。"""
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
