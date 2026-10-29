"""Read trusted self-evidence and commit one prepared persona group before cache updates.

读取可信自身证据，提交一个准备好的人格版本组后更新缓存。
"""
from __future__ import annotations

try:
    from ..core.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from ..core.persona import PERSONA_ORIGIN_DREAM, compose_seed_evolution
    from .ports import ArtifactCache, ArtifactStore, SourceStore
    from .self_impression import promote_self_candidates
except ImportError:
    from core.artifact import Artifact, Lineage, Strength, make, revise
    from core.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from core.persona import PERSONA_ORIGIN_DREAM, compose_seed_evolution
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore
    from maintain.self_impression import promote_self_candidates

from .persona_policy import TOP_N, prepare_persona


def compose(impressions: list[Artifact]) -> str:
    """Compose at most the existing top trusted self-behavior kinds / 组合至多既有上限的可信自身行为类别。"""
    kinds = list(dict.fromkeys(a.payload["bot_behavior"] for a in impressions
                              if trusted_self_impression(a)))[:TOP_N]
    return compose_behaviors(kinds)


def distill_self_persona(artifacts: ArtifactStore, sources: SourceStore, cache: ArtifactCache,
                        today: str | None = None) -> Artifact | None:
    """Read verified self-candidates, commit the prepared persona group, then cache / 读取已验证自身候选，提交准备好的人格版本组后更新缓存。"""
    candidates = promote_self_candidates(cache, sources, today)
    prepared = prepare_persona(candidates, list(cache.active("persona")))
    persona, plan = prepared.persona, prepared.revisions
    if persona is None:
        return None
    artifacts.commit_many(plan.rows(), op=plan.op, reason=plan.reason)
    if plan.writes:
        cache.put(persona)
        for write in plan.writes:
            if write.artifact.header.state != "active":
                cache.remove(write.artifact.header.id)
    return persona


def distill_persona(artifacts: ArtifactStore, sources: SourceStore, cache: ArtifactCache,
                    today: str | None = None,
                    only_umo: str = "") -> Artifact | None:
    """Preserve the legacy signature; user impressions are never persona evidence / 保留旧签名，用户印象不能成为人格证据。"""
    return distill_self_persona(artifacts, sources, cache, today)
