"""Own active-memory indices and their change marker; borrow a reader and never write storage.

管理有效记忆索引及变化标记，借用读取接口，不写入存储。
"""

from __future__ import annotations

from dataclasses import dataclass

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact

from .ports import ArtifactReader


@dataclass(frozen=True)
class _IndexKeys:
    """Prepared index keys; compute before modifying live state / 预先准备的索引键，在修改现有状态前计算。"""

    family: str
    level: str | None
    subject: str


def _index_keys(art: Artifact) -> _IndexKeys:
    """Validate fallible payload/key access before publication / 在发布前完成可能失败的内容和索引键读取。"""
    family = art.header.family
    hash(family)
    level = art.payload.get("level")
    return _IndexKeys(family, level if isinstance(level, str) and level else None,
                      str(art.header.subject_id or ""))


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
        """Prepare a complete replacement; a failed read/build preserves the live view.

        准备完整替换内容，读取或构造失败时保留现有视图；本缓存由同一进程执行线程使用。
        """
        prepared = Cache(self.artifacts)
        for art in self.artifacts.list(state="active"):
            prepared.put(art)
        self._items = prepared._items
        self._by_family = prepared._by_family
        self._by_level = prepared._by_level
        self._by_subject = prepared._by_subject
        self._version += 1 + prepared._version

    def put(self, art: Artifact) -> None:
        """Prepare keys, then replace active memory or remove inactive memory.

        先准备索引键，再替换有效记忆或移除非有效记忆；准备失败不改变现有索引。
        """
        node_id = art.header.id
        hash(node_id)
        keys = _index_keys(art)
        self.remove(node_id)
        if art.header.state != "active":
            return
        self._items[node_id] = art
        self._by_family.setdefault(keys.family, set()).add(node_id)
        if keys.level:
            self._by_level.setdefault(keys.level, set()).add(node_id)
        if keys.subject:
            self._by_subject.setdefault(keys.subject, set()).add(node_id)
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
        art = self._items.get(node_id)
        if art is None:
            return
        keys = _index_keys(art)
        self._items.pop(node_id)
        self._version += 1
        family_ids = self._by_family.get(keys.family)
        if family_ids is not None:
            family_ids.discard(node_id)
            if not family_ids:
                del self._by_family[keys.family]
        level = keys.level
        if level is not None:
            level_ids = self._by_level.get(level)
            if level_ids is not None:
                level_ids.discard(node_id)
                if not level_ids:
                    del self._by_level[level]
        subject = keys.subject
        if subject:
            subject_ids = self._by_subject.get(subject)
            if subject_ids is not None:
                subject_ids.discard(node_id)
                if not subject_ids:
                    del self._by_subject[subject]

    def size(self) -> int:
        """Count active cached memories / 统计有效缓存记忆数。"""
        return len(self._items)
