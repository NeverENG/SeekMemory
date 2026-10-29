"""Coalesce memory hits and repair cache after durable commits.

合并记忆命中，在持久提交后修复缓存；连接与缓存生命周期由调用方管理。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ports import ArtifactCache, ArtifactStore

try:
    from ..core.artifact import Artifact, revise
    from ..core.versioning import StateEvent
except ImportError:
    from core.artifact import Artifact, revise
    from core.versioning import StateEvent

MAX_WEIGHT = 3.0


@dataclass(frozen=True)
class _PendingHits:
    """Uncommitted hits, separate from cache repairs / 未提交命中，与缓存补偿分开。"""

    hits: int = 0
    at: str = ""


class CheckpointManager:
    """Own hit batching and process-local commit/cache recovery.

    管理命中批次及进程内提交、缓存恢复；不改变强化算法。
    """

    def __init__(self, artifacts: ArtifactStore, cache: ArtifactCache,
                 interval: int = 1800, cooldown_seconds: int | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache
        self.interval = max(1, int(interval))
        self.cooldown_seconds = max(0, int(interval if cooldown_seconds is None else cooldown_seconds))
        self.last_flush = time.monotonic()
        self._dirty: dict[str, _PendingHits] = {}
        self._repairs: set[str] = set()
        self._last_hit: dict[str, float] = {}

    def record(self, art: Artifact, at: str = "") -> bool:
        """Queue one accepted hit; ignore hits inside the cooldown.

        排队一次有效命中，冷却期内的命中忽略。
        """
        now = time.monotonic()
        last = self._last_hit.get(art.header.id)
        if last is not None and self.cooldown_seconds and now - last < self.cooldown_seconds:
            return False
        self._last_hit[art.header.id] = now
        delta = self._dirty.get(art.header.id, _PendingHits())
        self._dirty[art.header.id] = _PendingHits(delta.hits + 1, at or delta.at)
        return True

    def due(self) -> bool:
        """Whether unfinished work reached the flush interval / 未完成任务是否达到提交间隔。"""
        return bool(self.pending()) and time.monotonic() - self.last_flush >= self.interval

    def pending(self) -> int:
        """Count distinct IDs awaiting commit or cache repair / 按编号去重统计待提交或待补缓存的记忆。"""
        return len(self._dirty.keys() | self._repairs)

    def _repair(self, entity: str) -> None:
        """Refresh from the latest head; failures retain the repair marker.

        从最新版本刷新；失败时保留补偿标记，不再次强化。
        """
        latest = self.artifacts.get(entity)
        if latest is None:
            self.cache.remove(entity)
        else:
            self.cache.put(latest)
        self._repairs.discard(entity)

    def flush(self, now: str = "") -> int:
        """Return newly committed IDs; cache failures remain pending separately.

        返回新成功提交的记忆数；缓存失败独立等待补偿。
        """
        flushed = 0
        for entity in tuple(self._repairs):
            try:
                self._repair(entity)
            except Exception:
                continue
        for entity, delta in list(self._dirty.items()):
            if entity in self._repairs:
                continue
            try:
                # Storage owns the head; cache absence is not proof of deletion.
                # 数据库拥有当前版本，缓存未命中不表示记忆已删除。
                art = self.artifacts.get(entity)
                if art is None or art.header.state != "active":
                    self._dirty.pop(entity, None)
                    continue
                stamp = now or delta.at
                event = StateEvent(
                    id=f"ev_{time.time_ns()}_{entity}", entity_id=entity,
                    revision_seen=art.header.revision, op="reinforce",
                    delta={"hits": delta.hits, "weight": round(0.1 * delta.hits, 6)}, at=stamp)
                old = art.header.strength
                strength = replace(old, hits=int(old.hits or 0) + delta.hits,
                                   weight=min(MAX_WEIGHT, float(old.weight) + 0.1 * delta.hits))
                new = revise(art, strength=strength)
                self.artifacts.commit(new, expected_revision=art.header.revision,
                                      op="reinforce", reason="checkpoint",
                                      source_ids=tuple(art.header.lineage.sources),
                                      state_events=(event,))
            except Exception:
                continue
            # Consume only this committed batch before any fallible cache work.
            # 在可能失败的缓存操作之前，仅消费已经提交的批次。
            current = self._dirty[entity]
            if current.hits > delta.hits:
                self._dirty[entity] = replace(current, hits=current.hits - delta.hits)
            else:
                self._dirty.pop(entity, None)
            flushed += 1
            self._repairs.add(entity)
            try:
                self._repair(entity)
            except Exception:
                continue
        self.last_flush = time.monotonic()
        return flushed
