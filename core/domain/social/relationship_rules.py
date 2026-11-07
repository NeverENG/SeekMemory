"""Replay independently verified Source events into pure relationship snapshots."""

from __future__ import annotations
import hashlib
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterable

from .relationship import RELATIONSHIP_POLICY_VERSION, RelationshipSnapshot

VERIFIER_VERSION = "relationship-verifier-v2"

class RelationshipSignal(str, Enum):
    """Define derived relationship signal categories.

    定义派生关系信号类别。
    """
    POSITIVE = "positive"
    NEGATIVE = "negative"
    REPAIR = "repair"
    BOUNDARY_VIOLATION = "boundary_violation"


class RelationshipReason(str, Enum):
    """Define the supported categorical evidence reasons.

    定义受支持的分类证据原因。
    """
    FRIENDLY_GREETING = "friendly_greeting"
    GRATITUDE = "gratitude"
    CARE = "care"
    RESPECT = "respect"
    SUPPORT = "support"
    REPAIR = "repair"
    DISRESPECT = "disrespect"
    INSULT = "insult"
    THREAT = "threat"
    HARASSMENT = "harassment"


class RelationshipStrength(str, Enum):
    """Define mild and strong evidence categories.

    定义轻度及强烈证据类别。
    """
    MILD = "mild"
    STRONG = "strong"


class ConversationScope(str, Enum):
    """Define private, group and unknown observation scopes.

    定义私聊、群聊及未知观察范围。
    """
    PRIVATE = "private"
    GROUP = "group"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class EvidenceRule:
    """Classify a proposed event; never provide a score or interaction permission."""
    signal: RelationshipSignal


# Extraction derives a categorical signal from a reason; no V1 targets or caps.
EVIDENCE_RULES: dict[RelationshipReason, EvidenceRule] = {
    RelationshipReason.FRIENDLY_GREETING: EvidenceRule(RelationshipSignal.POSITIVE),
    RelationshipReason.GRATITUDE: EvidenceRule(RelationshipSignal.POSITIVE),
    RelationshipReason.CARE: EvidenceRule(RelationshipSignal.POSITIVE),
    RelationshipReason.RESPECT: EvidenceRule(RelationshipSignal.POSITIVE),
    RelationshipReason.SUPPORT: EvidenceRule(RelationshipSignal.POSITIVE),
    RelationshipReason.REPAIR: EvidenceRule(RelationshipSignal.REPAIR),
    RelationshipReason.DISRESPECT: EvidenceRule(RelationshipSignal.NEGATIVE),
    RelationshipReason.INSULT: EvidenceRule(RelationshipSignal.NEGATIVE),
    RelationshipReason.THREAT: EvidenceRule(RelationshipSignal.BOUNDARY_VIOLATION),
    RelationshipReason.HARASSMENT: EvidenceRule(RelationshipSignal.BOUNDARY_VIOLATION),
}

@dataclass(frozen=True)
class RelationshipCandidate:
    """Carry categorical Source-backed evidence pending independent verification."""
    subject_id: str
    reason: RelationshipReason
    strength: RelationshipStrength
    primary_source_id: str
    source_ids: tuple[str, ...]
    session_id: str
    scope: ConversationScope
    origin_artifact_id: str = ""
    origin_revision: int = 0





def relationship_event_id(candidate: RelationshipCandidate) -> str:
    raw = "\x1f".join((
        "relationship-v2", candidate.subject_id, candidate.reason.value,
        candidate.strength.value, *sorted(candidate.source_ids),
    ))
    return "re_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class VerifiedRelationshipEvent:
    event_id: str
    subject_id: str
    reason: RelationshipReason
    strength: RelationshipStrength
    scope: ConversationScope
    event_at: datetime
    primary_source_id: str
    source_ids: tuple[str, ...]
    repair_of: str = ""


_NEGATIVE_IMPACT = {
    RelationshipReason.DISRESPECT: 0.7,
    RelationshipReason.INSULT: 1.0,
    RelationshipReason.THREAT: 1.25,
    RelationshipReason.HARASSMENT: 1.25,
}
_WARMTH_IMPACT = {
    RelationshipReason.FRIENDLY_GREETING: 0.5,
    RelationshipReason.GRATITUDE: 0.8,
    RelationshipReason.CARE: 1.0,
    RelationshipReason.RESPECT: 0.3,
    RelationshipReason.SUPPORT: 0.8,
}
_TRUST_IMPACT = {
    RelationshipReason.CARE: 0.5,
    RelationshipReason.RESPECT: 1.0,
    RelationshipReason.SUPPORT: 0.8,
}


def _retention(age_days: float, half_life_days: float) -> float:
    if half_life_days == 0:
        return 1.0 if age_days == 0 else 0.0
    return 2.0 ** (-age_days / half_life_days)


def _event_key(event: VerifiedRelationshipEvent) -> tuple:
    """Break even timestamp/ID ties without depending on input order."""
    return (
        event.event_at, event.event_id, event.event_at.isoformat(),
        event.subject_id, event.primary_source_id, event.source_ids,
        event.reason.value, event.strength.value, event.scope.value, event.repair_of,
    )


def project_relationship(events: Iterable[VerifiedRelationshipEvent], as_of: datetime, policy: RelationshipScoringPolicy) -> RelationshipSnapshot:
    """Replay verified, attributable events at an explicit timezone-aware clock."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("relationship projection requires a timezone")
    chosen = []
    for event in events:
        if event.event_at.tzinfo is None or event.event_at.utcoffset() is None:
            raise ValueError("relationship evidence requires a timezone")
        if (event.event_at <= as_of and event.subject_id and event.primary_source_id
                and event.primary_source_id in event.source_ids and event.event_id
                and event.scope in (ConversationScope.PRIVATE, ConversationScope.GROUP)):
            chosen.append(event)
    chosen.sort(key=_event_key)
    if len({event.subject_id for event in chosen}) > 1:
        raise ValueError("relationship projection requires one subject")
    evaluated_at = as_of.isoformat()
    if not chosen:
        return RelationshipSnapshot(evaluated_at=evaluated_at)

    # One source backs at most one scored event, except a linked repair may
    # reuse its prior negative's sources as context with a fresh primary source.
    reasons_by_primary: dict[str, set[RelationshipReason]] = {}
    ids: dict[str, set[tuple]] = {}
    for event in chosen:
        reasons_by_primary.setdefault(event.primary_source_id, set()).add(event.reason)
        ids.setdefault(event.event_id, set()).add(_event_key(event))
    accepted = []
    used_sources: set[str] = set()
    negatives: dict[str, VerifiedRelationshipEvent] = {}
    for event in chosen:
        sources = set(event.source_ids)
        if (len(reasons_by_primary[event.primary_source_id]) != 1
                or len(ids[event.event_id]) != 1 or not all(sources)):
            continue
        prior = negatives.get(event.repair_of) if event.reason is RelationshipReason.REPAIR else None
        if event.reason is RelationshipReason.REPAIR and (
            prior is None or prior.subject_id != event.subject_id or prior.event_at >= event.event_at
            or event.primary_source_id in used_sources
        ):
            continue
        overlap = sources & used_sources
        if overlap and (prior is None or not overlap <= set(prior.source_ids)):
            continue
        accepted.append(event)
        used_sources.update(sources)
        if event.reason in _NEGATIVE_IMPACT:
            negatives[event.event_id] = event
    linked = {
        event.event_id: negatives[event.repair_of]
        for event in accepted if event.reason is RelationshipReason.REPAIR
    }
    if not accepted:
        return RelationshipSnapshot(evaluated_at=evaluated_at)

    scope_weights = {
        ConversationScope.PRIVATE: policy.private_weight,
        ConversationScope.GROUP: policy.group_weight,
    }
    familiarity_total = confidence_total = warmth_total = trust_total = 0.0
    tension_by_negative: dict[str, float] = {}
    repair_by_negative: dict[str, float] = {}
    stability_total = stability_max = 0.0
    positive_stability = negative_stability = 0.0
    for event in accepted:
        age = (as_of - event.event_at).total_seconds() / 86400
        base = (1 if event.strength == RelationshipStrength.MILD else 2) * scope_weights[event.scope]
        familiarity_total += base * _retention(age, policy.familiarity_half_life_days)
        confidence_total += base * _retention(age, policy.confidence_half_life_days)
        stable = base * _retention(age, policy.stability_half_life_days)
        stability_total += stable
        stability_max = max(stability_max, stable)
        if event.reason in _NEGATIVE_IMPACT:
            negative_stability += stable
            impact = base * _NEGATIVE_IMPACT[event.reason]
            trust_total -= impact * _retention(age, policy.trust_half_life_days)
            warmth_total -= impact * 0.5 * _retention(age, policy.warmth_half_life_days)
            cooled_age = max(0.0, age - policy.negative_cooldown_hours / 24)
            tension_by_negative[event.event_id] = impact * _retention(cooled_age, policy.tension_half_life_days)
        else:
            positive_stability += stable
            if event.reason == RelationshipReason.REPAIR:
                prior = linked[event.event_id]
                prior_impact = ((1 if prior.strength == RelationshipStrength.MILD else 2)
                                * scope_weights[prior.scope] * _NEGATIVE_IMPACT[prior.reason])
                if prior_impact:
                    trust_total += 0.3 * base * _retention(age, policy.trust_half_life_days)
                    warmth_total += 0.3 * base * _retention(age, policy.warmth_half_life_days)
                    # Repair removes at most 75% of this negative's remaining
                    # tension; subsequent repairs cannot subtract it again.
                    fraction = 0.75 * min(base / prior_impact, 1.0)
                    repair_by_negative[prior.event_id] = max(repair_by_negative.get(prior.event_id, 0.0), fraction)
            else:
                trust_total += base * _TRUST_IMPACT.get(event.reason, 0.0) * _retention(age, policy.trust_half_life_days)
                warmth_total += base * _WARMTH_IMPACT[event.reason] * _retention(age, policy.warmth_half_life_days)

    tension_total = sum(negative * (1 - repair_by_negative.get(event_id, 0.0))
                        for event_id, negative in tension_by_negative.items())
    repeated = stability_total - stability_max
    consistency = max(positive_stability, negative_stability) / stability_total if stability_total else 0.0
    rate = policy.learning_rate
    return RelationshipSnapshot(
        subject_id=accepted[-1].subject_id,
        familiarity=round(-math.expm1(-rate * familiarity_total), 6),
        trust=round(math.tanh(rate * trust_total), 6),
        warmth=round(math.tanh(rate * warmth_total), 6),
        tension=round(-math.expm1(-rate * tension_total), 6),
        stability=round(-math.expm1(-rate * repeated * consistency), 6),
        confidence=round(-math.expm1(-rate * confidence_total), 6),
        evidence_count=len(accepted),
        last_evidence_at=accepted[-1].event_at.isoformat(),
        evaluated_at=evaluated_at,
    )




@dataclass(frozen=True)
class RelationshipScoringPolicy:
    """Hold resolved scoring settings; parse configuration outside core.

    保存已解析评分设置，在 core 外解析配置。
    """

    version: str = RELATIONSHIP_POLICY_VERSION
    verifier_version: str = VERIFIER_VERSION
    learning_rate: float = 0.25
    private_weight: float = 1.0
    group_weight: float = 0.5
    unknown_weight: float = 0.5
    familiarity_half_life_days: float = 180
    trust_half_life_days: float = 180
    warmth_half_life_days: float = 45
    tension_half_life_days: float = 14
    stability_half_life_days: float = 90
    confidence_half_life_days: float = 90
    negative_cooldown_hours: float = 24

    def __post_init__(self) -> None:
        if self.version != RELATIONSHIP_POLICY_VERSION or self.verifier_version != VERIFIER_VERSION:
            raise ValueError("unsupported relationship policy version")
        for name in (
            "learning_rate", "private_weight", "group_weight", "unknown_weight",
            "familiarity_half_life_days", "trust_half_life_days", "warmth_half_life_days",
            "tension_half_life_days", "stability_half_life_days", "confidence_half_life_days",
            "negative_cooldown_hours",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be a non-negative number")
            if name.endswith("weight") or name == "learning_rate":
                if not 0.0 <= float(value) <= 1.0:
                    raise ValueError(f"{name} must be within [0, 1]")
