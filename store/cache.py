"""内存热数据缓存：只保留 state='active' 的记忆，并维护 family / level 索引。"""

from __future__ import annotations

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
except ImportError:  # 作为顶层 store 包导入（脚本 / 测试）
    from core.artifact import Artifact

try:
    from .db import DB
except ImportError:  # pragma: no cover - 兼容直接导入 store 目录
    from db import DB


class Cache:
    """进程内热数据；检索路径只读它，不查库。"""

    def __init__(self, db: DB) -> None:
        """绑定数据库，索引初始为空，调用 load() 后才可用。"""
        self.db = db
        self._items: dict[str, Artifact] = {}
        self._by_family: dict[str, set[str]] = {}
        self._by_level: dict[str, set[str]] = {}
        self._by_subject: dict[str, set[str]] = {}
        self._version = 0

    @property
    def version(self) -> int:
        """缓存内容的单调递增版本，供派生索引检测失效。"""
        return self._version

    def load(self) -> None:
        """清空后一次性载入所有 active 记忆。"""
        self._items.clear()
        self._by_family.clear()
        self._by_level.clear()
        self._by_subject.clear()
        self._version += 1
        for art in self.db.list(state="active"):
            self.put(art)

    def put(self, art: Artifact) -> None:
        """放入或替换一条记忆；非 active 的记忆会被移除。"""
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
        """按 id 取一条缓存记忆；没有则返回 None。"""
        return self._items.get(node_id)

    def active(self, family: str | None = None) -> list[Artifact]:
        """返回全部 active 记忆，可按 family 过滤。"""
        ids = set(self._items) if family is None else self._by_family.get(family, set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def by_level(self, level: str) -> list[Artifact]:
        """返回某个抽象层级的记忆（impression / scene / detail）。"""
        ids = self._by_level.get(level, set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def by_subject(self, subject_id: str) -> list[Artifact]:
        ids = self._by_subject.get(str(subject_id or ""), set())
        return [self._items[i] for i in sorted(ids) if i in self._items]

    def remove(self, node_id: str) -> None:
        """移除一条记忆并同步清理两个索引。"""
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
        """当前缓存的 active 记忆条数。"""
        return len(self._items)
