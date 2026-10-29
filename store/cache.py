"""Own active-memory indices and their change marker; borrow a reader and never write storage.

管理有效记忆索引及变化标记，借用读取接口，不写入存储。
"""

from __future__ import annotations

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact

from .ports import ArtifactReader


class Cache:
    """Own process-local active-memory indices; storage remains authoritative / 管理进程内有效记忆索引，存储仍是权威来源。"""

    def __init__(self, artifacts: ArtifactReader) -> None:
        self.artifacts = artifacts
        self._items: dict[str, Artifact] = {}
        self._by_family: dict[str, set[str]] = {}
        self._by_level: dict[str, set[str]] = {}
        self._by_subject: dict[str, set[str]] = {}
        self._version = 0

    @property
    def version(self) -> int:
        """Read a monotonic marker for derived-index invalidation / 读取供派生索引失效判断使用的单调标记。"""
        return self._version

    def load(self) -> None:
        """Rebuild active-memory indices from storage / 从存储重建有效记忆索引。"""
        self._items.clear()
        self._by_family.clear()
        self._by_level.clear()
        self._by_subject.clear()
        self._version += 1
        for art in self.artifacts.list(state="active"):
            self.put(art)

    def put(self, art: Artifact) -> None:
        """Publish active memory or remove an inactive value after database commit / 在数据库提交后发布有效记忆，或移除非有效记忆。"""
        node_id = art.header.id
        self.remove(node_id)
        if art.header.state != "active":
            return
        self._items[node_id] = art
        self._by_family.setdefault(art.header.family, set()).add(node_id)
        level = art.payload.get("level")
        if isinstance(level, str) and level:
            self._by_level.setdefault(level, set()).add(node_id)
        subject = str(art.header.subject_id or "")
        if subject:
            self._by_subject.setdefault(subject, set()).add(node_id)
        self._version += 1

    def get(self, node_id: str) -> Artifact | None:
        """Read cached memory; absence does not prove database absence / 读取缓存记忆，未命中不表示数据库不存在。"""
        return self._items.get(node_id)

    def active(self, family: str | None = None) -> list[Artifact]:
        """Read sorted active cached memories, optionally filtered by family / 按排序读取有效缓存记忆，可限定类型。"""
        ids = set(self._items) if family is None else self._by_family.get(family, set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def by_level(self, level: str) -> list[Artifact]:
        """Read sorted active cached memories at one abstraction level / 按排序读取一个抽象层级的有效缓存记忆。"""
        ids = self._by_level.get(level, set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def by_subject(self, subject_id: str) -> list[Artifact]:
        """Read sorted active cached memories about one subject / 按排序读取关于一个主体的有效缓存记忆。"""
        ids = self._by_subject.get(str(subject_id or ""), set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def remove(self, node_id: str) -> None:
        """Remove a cached memory and its family, level and subject indices / 移除缓存记忆及其类型、层级和主体索引。"""
        art = self._items.pop(node_id, None)
        if art is None:
            return
        self._version += 1
        family_ids = self._by_family.get(art.header.family)
        if family_ids is not None:
            family_ids.discard(node_id)
            if not family_ids:
                del self._by_family[art.header.family]
        level = art.payload.get("level")
        if isinstance(level, str):
            level_ids = self._by_level.get(level)
            if level_ids is not None:
                level_ids.discard(node_id)
                if not level_ids:
                    del self._by_level[level]
        subject = str(art.header.subject_id or "")
        if subject:
            subject_ids = self._by_subject.get(subject)
            if subject_ids is not None:
                subject_ids.discard(node_id)
                if not subject_ids:
                    del self._by_subject[subject]

    def size(self) -> int:
        """Count active cached memories / 统计有效缓存记忆数。"""
        return len(self._items)
