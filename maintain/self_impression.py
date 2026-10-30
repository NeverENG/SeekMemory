"""Read immutable paired evidence, prepare self-impression revisions and commit before cache.

读取不可变配对证据，准备自我印象版本并在缓存前提交。
"""
from __future__ import annotations

from .writer import MaintenanceWriter

from dataclasses import dataclass

try:
    from ..core.domain.memory.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.domain.character.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                     SELF_SUBJECT, confident, trusted_self_impression)
    from ..core.domain.memory.source import Source
    from .ports import ArtifactCache, ArtifactStore, SourceStore
except ImportError:
    from core.domain.memory.artifact import Artifact, Lineage, Strength, make, revise
    from core.domain.character.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                   SELF_SUBJECT, confident, trusted_self_impression)
    from core.domain.memory.source import Source
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore

MIN_HITS = MIN_EVIDENCE


from .self_impression_policy import (
    Observation, _pairs, _observations, _supported, prepare_self_impressions,
)


def build_self_impressions(artifacts: ArtifactStore, sources: SourceStore,
                           cache: ArtifactCache, min_hits: int = MIN_HITS,
                           today: str | None = None,
                           *, writer: MaintenanceWriter | None = None) -> int:
    """Read exact paired evidence, commit one prepared self-impression group and then cache / 读取精确配对证据，提交准备好的自我印象版本组后更新缓存。"""
    writer = writer or MaintenanceWriter(artifacts, cache)
    writer.ensure_ready()
    pool = cache.active("memory")
    ids = sorted({sid for art in pool for sid in art.header.lineage.sources})
    source_rows = sources.sources_by_ids(ids)
    episodes = {
        entity: artifacts.get(entity)
        for art in pool if _supported(art, source_rows)
        for entity in art.header.lineage.derived_from
    }
    plan = prepare_self_impressions(pool, source_rows, episodes, min_hits)
    writer.execute(plan)
    return len(plan.writes)


def promote_self_candidates(cache: ArtifactCache, sources, today: str | None = None) -> list[Artifact]:
    """Read trusted self-impressions and verify exact evidence before ranking / 读取可信自我印象，在排序前验证精确证据。"""
    pool = [art for art in cache.active("memory") if trusted_self_impression(art)]
    by_id = sources.sources_by_ids(sorted({s for a in pool for s in a.header.lineage.sources}))
    found = [art for art in pool if _supported(art, by_id)]
    found.sort(key=lambda a: (-a.header.strength.weight,
                              BEHAVIORS.index(a.payload["bot_behavior"]), a.header.id))
    return found
