from __future__ import annotations

import time
from dataclasses import replace
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


class CheckpointManager:
    def __init__(self, artifacts: ArtifactStore, cache: ArtifactCache, interval: int = 1800,
                 cooldown_seconds: int | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache
        self.interval = max(1, int(interval))
        self.cooldown_seconds = max(0, int(interval if cooldown_seconds is None else cooldown_seconds))
        self.last_flush = time.monotonic()
        self._dirty: dict[str, dict] = {}
        self._last_hit: dict[str, float] = {}

    def record(self, art: Artifact, at: str = "") -> bool:
        now = time.monotonic()
        last = self._last_hit.get(art.header.id)
        if last is not None and self.cooldown_seconds and now - last < self.cooldown_seconds:
            return False
        self._last_hit[art.header.id] = now
        if art.header.id not in self._dirty:
            self._dirty[art.header.id] = {"revision": art.header.revision, "hits": 0}
        self._dirty[art.header.id]["hits"] += 1
        if at:
            self._dirty[art.header.id]["at"] = at
        return True

    def due(self) -> bool:
        return bool(self._dirty) and time.monotonic() - self.last_flush >= self.interval

    def pending(self) -> int:
        return len(self._dirty)

    def flush(self, now: str = "") -> int:
        flushed = 0
        for entity, delta in list(self._dirty.items()):
            art = self.cache.get(entity)
            if art is None:
                self._dirty.pop(entity, None)
                continue
            hits = int(delta.get("hits") or 0)
            if hits <= 0:
                self._dirty.pop(entity, None)
                continue
            stamp = now or str(delta.get("at") or "")
            event = StateEvent(
                id=f"ev_{time.time_ns()}_{entity}", entity_id=entity,
                revision_seen=art.header.revision, op="reinforce",
                delta={"hits": hits, "weight": round(0.1 * hits, 6)}, at=stamp)
            old = art.header.strength
            strength = replace(old, hits=int(old.hits or 0) + hits,
                               weight=min(MAX_WEIGHT, float(old.weight) + 0.1 * hits))
            new = revise(art, strength=strength)
            try:
                self.artifacts.commit(new, expected_revision=art.header.revision,
                                  op="reinforce", reason="checkpoint",
                                  source_ids=tuple(art.header.lineage.sources),
                                  state_events=(event,))
                self.cache.put(new)
                flushed += 1
            except Exception:
                continue
            self._dirty.pop(entity, None)
        self.last_flush = time.monotonic()
        return flushed
