"""Prepare existing seed-preserving persona revisions from supplied verified candidates.

从给定已验证候选准备保留设定的既有人格版本，不执行读写。
"""
from __future__ import annotations

try:
    from ..core.domain.memory.artifact import Artifact, Lineage, Strength, make, revise
    from ..core.domain.character.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from ..core.domain.character.persona import PERSONA_ORIGIN_DREAM, compose_seed_evolution
    from .ports import ArtifactCache, ArtifactStore, SourceStore
except ImportError:
    from core.domain.memory.artifact import Artifact, Lineage, Strength, make, revise
    from core.domain.character.bot_behavior import SELF_SUBJECT, compose_behaviors, trusted_self_impression
    from core.domain.character.persona import PERSONA_ORIGIN_DREAM, compose_seed_evolution
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore

from dataclasses import dataclass
from .plans import RevisionPlan, RevisionWrite

TOP_N = 3


@dataclass(frozen=True)
class PersonaPlan:
    """Hold the prepared persona and atomic revision group / 保存已准备人格及其原子版本组。"""
    persona: Artifact | None
    revisions: RevisionPlan


def prepare_persona(candidates: list[Artifact], old_personas: list[Artifact]) -> PersonaPlan:
    """Prepare existing seed-preserving persona and duplicate retirement without writes / 准备既有保留设定的人格及重复人格停用，不执行写入。"""
    chosen = []
    seen = set()
    for art in candidates:
        kind = art.payload["bot_behavior"]
        if kind not in seen:
            seen.add(kind)
            chosen.append(art)
        if len(chosen) == TOP_N:
            break
    if not chosen:
        return PersonaPlan(None, RevisionPlan((), "promote", "self-only stable persona and consolidation"))
    kinds = [a.payload["bot_behavior"] for a in chosen]
    old = sorted(old_personas, key=lambda a: (
        a.header.subject_id != SELF_SUBJECT, a.header.time.created, a.header.id))
    base = old[0] if old else None
    behavior_text = compose_behaviors(kinds)
    has_seed_base = base is not None and bool(
        base.payload.get("origin") or base.payload.get("seed_id")
    )
    if has_seed_base:
        base_text = str(base.payload.get("base_text") or base.payload.get("text") or "")
        payload = {
            "text": compose_seed_evolution(base_text, behavior_text),
            "origin": PERSONA_ORIGIN_DREAM,
            "base_text": base_text,
            "behaviors": kinds,
            "seed_id": str(base.payload.get("seed_id") or ""),
            "seed_version": str(base.payload.get("seed_version") or ""),
            "seed_license": str(base.payload.get("seed_license") or ""),
            "seed_source": str(base.payload.get("seed_source") or ""),
            "persona_name": str(base.payload.get("persona_name") or ""),
            "style": dict(base.payload.get("style") or {}),
            "boundaries": list(base.payload.get("boundaries") or []),
            "corpus_count": int(base.payload.get("corpus_count") or 0),
            "corpus_hash": str(base.payload.get("corpus_hash") or ""),
            "content_rating": str(base.payload.get("content_rating") or ""),
            "locale": str(base.payload.get("locale") or ""),
        }
    else:
        payload = {"text": behavior_text, "behaviors": kinds}
    lineage = Lineage(
        sources=tuple(sorted({s for a in chosen for s in a.header.lineage.sources})),
        derived_from=tuple(a.header.id for a in chosen),
    )
    strength = Strength(weight=max(a.header.strength.weight for a in chosen),
                        confidence=min(a.header.strength.confidence for a in chosen),
                        hits=sum(a.header.strength.hits for a in chosen))
    kw = dict(subject_id=SELF_SUBJECT, scope="shared", shareable="public",
              said_by="inferred", lineage=lineage, strength=strength)
    unchanged = (base is not None and base.payload == payload
                 and all(getattr(base.header, key) == value for key, value in kw.items()
                         if key != "strength"))
    persona = base if unchanged else (revise(base, payload, **kw) if base
                                     else make("persona", payload, **kw))
    writes = [] if unchanged else [(persona, base.header.revision if base else 0, lineage.sources)]
    retired = [revise(a, state="merged") for a in old[1:]]
    writes.extend((a, a.header.revision - 1, a.header.lineage.sources) for a in retired)
    return PersonaPlan(persona, RevisionPlan(tuple(
        RevisionWrite(art, expected, tuple(sources)) for art, expected, sources in writes
    ), "promote", "self-only stable persona and consolidation"))
