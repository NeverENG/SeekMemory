"""Read and write trees through injected ports; separate writes are not one transaction.

通过注入接口读写树结构，各写入步骤不是整体事务，资源由调用方管理。
"""

from __future__ import annotations

try:
    from ..app.ports import TreeArtifactStore, TreeCache
    from ..app.revision_plan import prepare_revision
    from ..core.domain.memory.artifact import Artifact, revise
    from ..core.domain.memory.tree import ancestor_ids, parent_id, tree_child_kind
except ImportError:
    from app.ports import TreeArtifactStore, TreeCache
    from app.revision_plan import prepare_revision
    from core.domain.memory.artifact import Artifact, revise
    from core.domain.memory.tree import ancestor_ids, parent_id, tree_child_kind

class TreeService:
    """Read tree memory and commit before separate cache, parent and edge writes; failures propagate / 读取树记忆，提交后分别写缓存、父节点和连接，失败向上传递。"""

    def __init__(self, artifacts: TreeArtifactStore,
                 cache: TreeCache | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache

    def _get(self, node_id: str) -> Artifact | None:
        """Read cache first, then storage without cache fill / 先读缓存，再读存储，不回填缓存。"""
        art = self.cache.get(node_id) if self.cache is not None else None
        if art is not None:
            return art
        return self.artifacts.get(node_id)

    def _persist(self, art: Artifact) -> None:
        """Prepare and commit a revision, then update optional cache / 准备并提交版本，再更新可选缓存。"""
        prepared = prepare_revision(art, self.artifacts)
        art, expected, op = prepared.artifact, prepared.expected_revision, prepared.op
        self.artifacts.commit(
            art,
            expected_revision=expected,
            op=op,
            reason="tree",
            source_ids=tuple(art.header.lineage.sources),
        )
        if self.cache is not None:
            self.cache.put(art)

    def parent_id(self, node_id: str) -> str | None:
        """Read one unambiguous stored parent / 读取唯一且明确的已存父节点。"""
        return parent_id(node_id, self.artifacts)

    def ancestor_ids(self, node_id: str, *, max_depth: int = 32) -> tuple[str, ...]:
        """Read bounded ancestors without changing storage / 有界读取祖先，不修改存储。"""
        return ancestor_ids(node_id, self.artifacts, max_depth=max_depth)

    def children(self, node_id: str) -> list[Artifact]:
        """Read distinct existing children from stored tree edges / 根据已存树连接读取去重且仍存在的子节点。"""
        if not node_id:
            return []
        wanted = tree_child_kind(node_id)
        result: list[Artifact] = []
        seen: set[str] = set()
        for edge in self.artifacts.edges_of(node_id):
            if len(edge) < 3:
                continue
            other, kind = edge[0], edge[1]
            if kind != wanted or not other or other in seen:
                continue
            art = self._get(other)
            if art is not None:
                seen.add(other)
                result.append(art)
        return result

    def impressions(self) -> list[Artifact]:
        """Read active impressions; fall back to storage only for an empty cached level / 读取有效印象，仅在缓存层级为空时回退存储。"""
        arts = list(self.cache.by_level("impression")) if self.cache else []
        if not arts:
            arts = list(self.artifacts.list("memory", "active"))
        return [
            art for art in arts
            if art.header.family == "memory"
            and art.header.state == "active"
            and art.payload.get("level") == "impression"
        ]

    def add_under(self, child: Artifact, parent_id: str | None) -> Artifact:
        """Commit a child, then write parent and edge separately; return the original input / 提交子节点，再分别写父节点及连接，返回原输入对象。"""
        if parent_id is not None and parent_id == child.header.id:
            raise ValueError("node cannot be its own parent")
        self._persist(child)
        self.artifacts.set_parent(child.header.id, parent_id)
        if parent_id is not None:
            self.artifacts.add_edge(
                parent_id, child.header.id, tree_child_kind(parent_id), 1.0
            )
        return child
