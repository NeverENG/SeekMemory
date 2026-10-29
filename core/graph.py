"""Read and write graph edges through an injected repository; callers own storage and its lifetime.

通过注入仓储读写图连接，调用方拥有存储及其生命周期。
"""

from __future__ import annotations

from dataclasses import dataclass

from .ports import GraphArtifactStore


@dataclass(frozen=True)
class ArtifactEdge:
    """Represent one directed relationship between Artifacts.

    表示 Artifact 之间的一条有向关系。
    """

    source: str
    target: str
    kind: str
    weight: float


KINDS = ("similar", "causal", "temporal")


class Graph:
    """Coordinate graph edge validation and neighbour views; do not own storage.

    协调图连接校验及邻居视图，不拥有存储。
    """

    def __init__(self, artifacts: GraphArtifactStore) -> None:
        self.artifacts = artifacts

    def link(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Validate endpoints/kind and delegate an edge upsert; storage errors propagate.

        校验两端及类别后委托连接写入或更新，存储错误向上传递。
        """
        if kind not in KINDS:
            raise ValueError(f"未知边类型：{kind!r}，可选：{'|'.join(KINDS)}")
        if not src or not dst:
            raise ValueError("边的两端 id 都不能为空")
        if src == dst:
            raise ValueError("不能把节点连到自己")
        self.artifacts.add_edge(src, dst, kind, float(weight))

    def link_causal(self, src: str, dst: str, weight: float = 1.0) -> None:
        """Write an explicit causal edge; automatic causal inference is not performed.

        写入显式因果边，不执行自动因果推断。
        """
        self.link(src, dst, "causal", weight)

    def degree(self, node_id: str) -> int:
        """Count every stored edge kind for a node, including tree links.

        统计节点的全部存储连接类别，包括树连接。
        """
        if not node_id or self.artifacts is None:
            return 0
        return len(self.artifacts.edges_of(node_id))

    def neighbours(
        self,
        node_id: str,
        kinds: tuple[str, ...] = KINDS,
    ) -> list[tuple[str, float]]:
        """Filter kinds, keep each neighbour's maximum weight and sort by identity.

        筛选类别，为每个邻居保留最大权重并按编号排序。
        """
        if not node_id or self.artifacts is None:
            return []
        allowed = set(kinds)
        best: dict[str, float] = {}
        for edge in self.artifacts.edges_of(node_id):
            if len(edge) < 3:
                continue
            other, kind, weight = edge[0], edge[1], edge[2]
            if not other or other == node_id or kind not in allowed:
                continue
            try:
                value = float(weight)
            except (TypeError, ValueError):
                continue
            if other not in best or value > best[other]:
                best[other] = value
        return sorted(best.items())
