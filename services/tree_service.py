"""Read trees and submit evidence-backed tree changes through injected ports.

通过注入接口读取树并提交带证据的原子树变更。
"""

from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json

try:
    from ..app.ports import TreeArtifactStore, TreeCache
    from ..app.revision_plan import prepare_revision
    from ..core.domain.memory.artifact import Artifact
    from ..core.domain.memory.tree import ancestor_ids, parent_ids
    from ..core.domain.memory.tree_change import TreeChange, TreeLink, TreeRevision
except ImportError:
    from app.ports import TreeArtifactStore, TreeCache
    from app.revision_plan import prepare_revision
    from core.domain.memory.artifact import Artifact
    from core.domain.memory.tree import ancestor_ids, parent_ids
    from core.domain.memory.tree_change import TreeChange, TreeLink, TreeRevision

class TreeService:
    """Read tree memory and commit version and edges together / 读取树记忆并一起提交版本与连接。"""

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
        """Commit a child revision and its parent links together; no single-parent write.

        先验证父节点，再原子提交子节点及树边；不写单值父字段。
        """
        parent_ids = tuple(dict.fromkeys(parents))
        intent = json.dumps((asdict(child), sorted(parent_ids)), ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"), allow_nan=False)
        operation_id = sha256(intent.encode("utf-8")).hexdigest()
        if self.artifacts.tree_operation_done(operation_id):
            if self.cache is not None:
                self.cache.load()
            return child
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
        prepared = prepare_revision(child, self.artifacts)
        old_edges = self.artifacts.tree_snapshot(child.header.id)
        existing_links = {link.parent: link for link in old_edges}
        desired = tuple(sorted(set(existing_links) | set(parent_ids)))
        observed_ids = {child.header.id, *desired}
        observed = tuple(sorted((node_id,
                                  (current.header.revision if (current := self.artifacts.get(node_id)) else 0))
                                 for node_id in observed_ids))
        change = TreeChange(
            operation_id,
            (TreeRevision(prepared.artifact, prepared.expected_revision,
                          tuple(prepared.artifact.header.lineage.sources)),),
            observed,
            ((child.header.id, old_edges),),
            ((child.header.id, tuple(existing_links.get(parent_id, TreeLink(parent_id, child.header.id))
                                     for parent_id in desired)),),
            prepared.op, "tree",
        )
        self.artifacts.commit_tree_change(change)
        if self.cache is not None:
            try:
                self.cache.put(self.artifacts.get(child.header.id))
            except Exception:
                # The database is authoritative; retry from its head, never the prepared snapshot.
                self.cache.load()
                raise
        return child
