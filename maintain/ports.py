"""Required maintenance capabilities; reuse existing repository/cache declarations.

维护所需外部能力，复用既有仓储及缓存声明，不实现写入或管理资源。
"""
from __future__ import annotations

from typing import Protocol

try:
    from ..app.ports import ArtifactCache, ArtifactStore, SourceStore
    from ..core.domain.memory.artifact import Artifact
    from ..core.port.tree import TreeEdgeReader
except ImportError:
    from app.ports import ArtifactCache, ArtifactStore, SourceStore
    from core.domain.memory.artifact import Artifact
    from core.port.tree import TreeEdgeReader


class DreamImpactStore(TreeEdgeReader, Protocol):
    """Only current heads and bounded reverse lineage for offline review / 仅供离线复核的当前节点与有界反向血缘。"""

    def get(self, node_id: str) -> Artifact | None: ...
    def active_dependents(self, node_id: str, limit: int) -> list[str]: ...
    def current_evidence_ids(self, node_id: str, limit: int) -> list[str]: ...


__all__ = ["ArtifactCache", "ArtifactStore", "SourceStore"]
