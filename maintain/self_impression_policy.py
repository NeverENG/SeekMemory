"""Validate supplied exact reply pairs and prepare evidence-backed self-impressions.

校验给定精确回复对并准备有证据的自我印象，不读取外部资源或写入。
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from ..core.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                     SELF_SUBJECT, confident, trusted_self_impression)
    from ..core.source import Source
    from .ports import ArtifactCache, ArtifactStore, SourceStore
except ImportError:
    from core.artifact import Artifact, Lineage, Strength, make, revise
    from core.bot_behavior import (BEHAVIORS, BEHAVIOR_TEXT, MIN_EVIDENCE,
                                   SELF_SUBJECT, confident, trusted_self_impression)
    from core.source import Source
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore

from .plans import RevisionPlan, RevisionWrite

def _pairs(ids: tuple[str, ...], sources: dict[str, Source]) -> dict[str, tuple[str, str]]:
    """Accept only existing same-session assistant/user pairs with exact reply_to / 仅接受已存在且 reply_to 精确匹配的同会话助手及用户对。"""
    result = {}
    for sid in ids:
        assistant = sources.get(sid)
        if assistant is None or assistant.role != "assistant":
            continue
        parent = sources.get(assistant.reply_to or "")
        if (parent is not None and parent.role == "user" and parent.id in ids
                and parent.session_id == assistant.session_id):
            result[sid] = (parent.id, sid)
    return result


@dataclass(frozen=True)
class Observation:
    """Hold one distinct episode and its paired evidence / 保存一次不同事件及其配对证据。"""
    episode_id: str
    sources: tuple[str, str]
    confidence: float


def _observations(art: Artifact, sources: dict[str, Source]) -> dict[str, Observation]:
    """Validate one original confident behavior observation from supplied evidence / 根据给定证据校验一次原始高置信行为观察。"""
    h = art.header
    if (art.payload.get("level") not in ("scene", "detail", "fact")
            or h.lineage.derived_from or not confident(h.strength.confidence)):
        return {}
    pairs = _pairs(h.lineage.sources, sources)
    if len(pairs) != 1 or len(set(h.lineage.sources)) != 2:
        return {}
    return {sid: Observation(h.id, pair, float(h.strength.confidence))
            for sid, pair in pairs.items()}


def _supported(art: Artifact, sources: dict[str, Source]) -> bool:
    """Require trusted self-impression and the existing minimum independent evidence / 要求可信自我印象及既有最少独立证据。"""
    return (trusted_self_impression(art)
            and len(_pairs(art.header.lineage.sources, sources)) >= MIN_EVIDENCE)


def prepare_self_impressions(pool: list[Artifact], source_rows: dict[str, Source],
                             episodes: dict[str, Artifact | None], min_hits: int) -> RevisionPlan:
    """Group supplied verified episodes and prepare deterministic self-impression revisions / 对给定已验证事件分组，并准备确定性自我印象版本。"""
    groups: dict[str, dict[str, Observation]] = {key: {} for key in BEHAVIORS}
    old_by_kind: dict[str, Artifact] = {}
    for art in sorted(pool, key=lambda a: a.header.id):
        kind = art.payload.get("bot_behavior")
        if not isinstance(kind, str) or kind not in groups:
            continue
        if _supported(art, source_rows):
            old_by_kind.setdefault(kind, art)
            # Old impressions carry original evidence, never an extra count.
            # 旧印象仅携带原事件证据，本身不增加计数。
            for episode_id in art.header.lineage.derived_from:
                episode = episodes.get(episode_id)
                if episode is not None and episode.payload.get("bot_behavior") == kind:
                    for sid, observation in _observations(episode, source_rows).items():
                        groups[kind].setdefault(sid, observation)
        elif art.header.state == "active":
            for sid, observation in _observations(art, source_rows).items():
                groups[kind].setdefault(sid, observation)
    writes = []
    for kind, observed in groups.items():
        if len(observed) < max(MIN_EVIDENCE, int(min_hits)):
            continue
        observations = [observed[sid] for sid in sorted(observed)]
        lineage = Lineage(
            sources=tuple(dict.fromkeys(s for o in observations for s in o.sources)),
            derived_from=tuple(sorted({o.episode_id for o in observations})),
        )
        payload = {"text": BEHAVIOR_TEXT[kind], "level": "impression",
                   "shape": "pattern", "chrono": "once", "about": "self",
                   "bot_behavior": kind, "first": False}
        strength = Strength(weight=1.5 + min(1.5, 0.1 * (len(observed) - MIN_EVIDENCE)),
                            confidence=min(o.confidence for o in observations),
                            hits=len(observed))
        old = old_by_kind.get(kind)
        if old is not None and old.payload == payload and old.header.lineage == lineage:
            continue
        kw = dict(scope="shared", said_by="inferred", shareable="public",
                  subject_id=SELF_SUBJECT, strength=strength, lineage=lineage)
        art = revise(old, payload=payload, **kw) if old else make("memory", payload, **kw)
        writes.append((art, old.header.revision if old else 0, lineage.sources))
    return RevisionPlan(tuple(RevisionWrite(art, revision, sources) for art, revision, sources in writes),
                        "revise", "evidence-backed self-impressions")
