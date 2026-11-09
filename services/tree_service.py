"""Read and write trees through injected ports; separate writes are not one transaction.

通过注入接口读写树结构，各写入步骤不是整体事务，资源由调用方管理。
"""

from __future__ import annotations

try:
    from ..app.ports import TreeArtifactStore, TreeCache
    from ..app.revision_plan import prepare_revision
    from ..core.domain.memory.artifact import Artifact, revise
    from ..core.domain.memory.tree import ancestor_ids, parent_ids, tree_child_kind
except ImportError:
    from app.ports import TreeArtifactStore, TreeCache
    from app.revision_plan import prepare_revision
    from core.domain.memory.artifact import Artifact, revise
    from core.domain.memory.tree import ancestor_ids, parent_ids, tree_child_kind

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

    def legacy_gap_count(self) -> int:
        """Expose only the count of unmigrated legacy links / 仅暴露未迁移旧连接的数量。"""
        return self.artifacts.legacy_tree_gap_count()

    def tree_parents(self, node_id: str, limit: int) -> list[str]:
        """Provide current active parent IDs to the pure ancestry traversal / 向纯祖先遍历提供当前有效父节点。"""
        return self.artifacts.active_tree_parents(node_id, limit)

    def parents(self, node_id: str, *, limit: int = 8) -> tuple[str, ...]:
        """Read bounded current active parents from tree edges / 从树边限量读取当前有效父节点。"""
        return parent_ids(node_id, self, limit=limit)

    def ancestor_ids(self, node_id: str, *, max_depth: int = 3,
                     max_visits: int = 32, max_parents: int = 8) -> tuple[str, ...]:
        """Read multi-parent ancestry without writes / 只读查询多父祖先。"""
        return ancestor_ids(node_id, self, max_depth=max_depth,
                            max_visits=max_visits, max_parents=max_parents)

    def children(self, node_id: str, *, limit: int = 8) -> list[Artifact]:
        """Read bounded active children, cache first; no cache fill.

        有界读取当前有效子节点，先缓存后仓储，不回填缓存。
        """
        if not node_id:
            return []
        result: list[Artifact] = []
        for child_id in self.artifacts.active_tree_children(node_id, limit):
            art = self._get(child_id)
            if art is not None:
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

    def add_under(self, child: Artifact, parents: tuple[str, ...]) -> Artifact:
        """Validate all parents, commit child and add each edge; no single-parent write.

        先验证所有父节点，再提交子节点及逐条写边；不写单值父字段。
        """
        parent_ids = tuple(dict.fromkeys(parents))
        if len(parent_ids) > 8:
            raise ValueError("too many parents")
        if child.header.id in parent_ids:
            raise ValueError("node cannot be its own parent")
        for parent_id in parent_ids:
            parent = self.artifacts.get(parent_id)
            if (parent is None or parent.header.family != "memory"
                    or parent.header.state != "active"
                    or (parent.header.subject_id, parent.header.scope) !=
                    (child.header.subject_id, child.header.scope)):
                raise ValueError("parent identity or state invalid")
            if child.header.id in self.ancestor_ids(parent_id, max_depth=3,
                                                     max_visits=32, max_parents=8):
                raise ValueError("tree cycle")
        self._persist(child)
        for parent_id in parent_ids:
            self.artifacts.add_edge(parent_id, child.header.id,
                                    tree_child_kind(parent_id), 1.0)
        return child
