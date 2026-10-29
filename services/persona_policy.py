"""Compute persona evidence and revisions without model calls or writes.

计算人格证据及新版本，不调用模型或执行写入；输入由编排方读取并提供。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from collections.abc import Iterable

try:
    from ..app.persona_synthesis import PersonaEvidence
    from ..core.artifact import Artifact, Lineage, Strength, content_of, revise
    from ..core.bot_behavior import SELF_SUBJECT
    from ..core.persona import PERSONA_SYNTHESIS_VERSION
except ImportError:
    from app.persona_synthesis import PersonaEvidence
    from core.artifact import Artifact, Lineage, Strength, content_of, revise
    from core.bot_behavior import SELF_SUBJECT
    from core.persona import PERSONA_SYNTHESIS_VERSION


@dataclass(frozen=True)
class NormalizedWeight:
    """Bounded weight and whether it needed correction / 限定后的权重及是否发生纠正。"""

    value: float
    corrected: bool


def relationship_weight(raw: object, default: float) -> NormalizedWeight:
    """Normalize one configured weight without logging / 规范化一个配置权重，不记录日志。"""
    invalid = False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value, invalid = default, True
    if not math.isfinite(value):
        value, invalid = default, True
    clamped = max(0.0, min(1.0, value))
    return NormalizedWeight(clamped, invalid or clamped != value)


def persona_evidence(candidates: Iterable[Artifact], pool: Iterable[Artifact],
                     limit: int) -> list[PersonaEvidence]:
    """Select bounded self evidence and public shared memories, preserving order.

    按原顺序限量选择自身证据与公开共享记忆；私有记忆不能影响全局人格。
    """
    out: list[PersonaEvidence] = []
    seen: set[str] = set()

    def add(art: Artifact, kind: str) -> None:
        """Add evidence once within the existing collection limit.

        在既有收集上限内加入不重复证据。
        """
        if len(out) >= limit or art.header.id in seen:
            return
        try:
            text = content_of(art)
        except Exception:
            return
        text = str(text or "").strip()
        if not text:
            return
        out.append(PersonaEvidence(
            id=art.header.id, kind=kind, text=text,
            source_ids=tuple(art.header.lineage.sources),
        ))
        seen.add(art.header.id)

    for art in candidates:
        add(art, "self_impression")
    shared = [art for art in pool if art.header.family == "memory"
              and art.header.scope == "shared" and art.header.shareable != "secret"
              and str(art.payload.get("level") or "") in ("scene", "detail", "fact", "impression")]
    shared.sort(key=lambda art: (
        -float(art.header.strength.weight or 0), str(art.header.time.updated or ""), art.header.id,
    ))
    for art in shared:
        add(art, f"memory:{art.payload.get('level')}")
    return out


def persona_revision(current: Artifact, draft: dict,
                     evidence: list[PersonaEvidence]) -> Artifact:
    """Prepare the next persona revision; the caller owns CAS commit.

    准备下个人格版本，由调用方负责按预期版本提交。
    """
    payload = dict(current.payload)
    payload.update({
        "text": draft["persona"], "origin": "dream", "synthesis": PERSONA_SYNTHESIS_VERSION,
        "style": draft["style"], "boundaries": draft["boundaries"],
        "change_reason": draft["change_reason"],
    })
    for key in ("corpus", "behaviors", "base_text"):
        payload.pop(key, None)
    sources = tuple(sorted({source for item in evidence for source in item.source_ids if source}))
    confidence = max(0.9, min(1.0, float(current.header.strength.confidence or 0.9)))
    strength = Strength(
        weight=float(current.header.strength.weight or 1.0), confidence=confidence,
        hits=int(current.header.strength.hits or 0) + len(evidence),
    )
    return revise(
        current, payload=payload, subject_id=SELF_SUBJECT, scope="shared", shareable="public",
        said_by="inferred", lineage=Lineage(sources=sources, derived_from=tuple(item.id for item in evidence)),
        strength=strength,
    )
