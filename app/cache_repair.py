"""Repair committed IDs from current database heads; business plans stay external.

从数据库当前版本补偿已提交编号，业务计划留在外部用例；资源由组装方管理。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import ArtifactStore, ArtifactCache


class CacheRepairs:
    """Own deduplicated committed-ID repairs and generations for reentrant marks.

    管理按编号去重的已提交缓存补偿，并以代次保留补偿期间重新标记的同编号工作。
    """

    def __init__(self, artifacts: ArtifactStore, cache: ArtifactCache | None) -> None:
        self.artifacts = artifacts
        self.cache = cache
        self._pending: dict[str, tuple[int, frozenset[object]]] = {}
        self._serial = 0
        self._repairing: set[str] = set()

    def mark(self, entity: str, owner: object | None = None) -> None:
        """Mark only after a durable commit; retain any later mark during repair.

        仅在持久提交后标记；补偿期间的后续标记必须保留。
        """
        self._serial += 1
        owners = self._pending.get(entity, (0, frozenset()))[1] | {owner}
        self._pending[entity] = self._serial, frozenset(owners)

    def ids(self, owner: object | None = None) -> frozenset[str]:
        """Read distinct pending committed IDs / 读取不同的待补偿已提交编号。"""
        return frozenset(entity for entity, (_generation, owners) in self._pending.items()
                         if owner is None or owner in owners)

    def repair(self, entity: str) -> bool:
        """Publish the latest head; remove its mark only if no new work arrived.

        发布最新版本，仅在无新工作到来时移除标记；失败抛错并保留标记。
        """
        if entity not in self._pending:
            return True
        if entity in self._repairing:
            return False
        generation = self._pending[entity]
        self._repairing.add(entity)
        try:
            if self.cache is not None:
                latest = self.artifacts.get(entity)
                if latest is None or latest.header.state != "active":
                    self.cache.remove(entity)
                else:
                    self.cache.put(latest)
            if self._pending.get(entity) == generation:
                self._pending.pop(entity, None)
                return True
            return False
        finally:
            self._repairing.discard(entity)

    def retry(self) -> int:
        """Attempt every pending ID once; ordinary failures remain pending.

        对每个待处理编号尝试一次，普通失败继续待处理；不提交记忆或调用模型。
        """
        completed = 0
        for entity in tuple(self._pending):
            try:
                completed += int(self.repair(entity))
            except Exception:
                continue
        return completed
