"""Prepare versioned relationship evidence plans without reading or writing resources.

准备带版本的关系证据计划，不读写资源。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from .relationship import (
    RELATIONSHIP_POLICY_VERSION,
    RelationshipBand,
    RelationshipSnapshot,
    band_for,
)

# Internal smoothing prior for confidence; not an evidence-admission threshold.
_CONFIDENCE_PRIOR_COUNT = 2.0


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
    """Describe target affinity and per-cycle caps for an evidence category.

    描述证据类别的目标亲近度及每轮上限。
    """
    signal: RelationshipSignal
    mild_target: float
    strong_target: float
    max_per_cycle: int


EVIDENCE_RULES: dict[RelationshipReason, EvidenceRule] = {
    RelationshipReason.FRIENDLY_GREETING: EvidenceRule(
        RelationshipSignal.POSITIVE, 0.35, 0.50, 1
    ),
    RelationshipReason.GRATITUDE: EvidenceRule(
        RelationshipSignal.POSITIVE, 0.35, 0.70, 2
    ),
    RelationshipReason.CARE: EvidenceRule(
        RelationshipSignal.POSITIVE, 0.40, 0.75, 1
    ),
    RelationshipReason.RESPECT: EvidenceRule(
        RelationshipSignal.POSITIVE, 0.45, 0.80, 1
    ),
    RelationshipReason.SUPPORT: EvidenceRule(
        RelationshipSignal.POSITIVE, 0.50, 0.85, 1
    ),
    RelationshipReason.REPAIR: EvidenceRule(
        RelationshipSignal.REPAIR, 0.70, 1.00, 1
    ),
    RelationshipReason.DISRESPECT: EvidenceRule(
        RelationshipSignal.NEGATIVE, -0.35, -0.60, 2
    ),
    RelationshipReason.INSULT: EvidenceRule(
        RelationshipSignal.NEGATIVE, -0.50, -0.80, 2
    ),
    RelationshipReason.THREAT: EvidenceRule(
        RelationshipSignal.BOUNDARY_VIOLATION, -0.75, -1.00, 1
    ),
    RelationshipReason.HARASSMENT: EvidenceRule(
        RelationshipSignal.BOUNDARY_VIOLATION, -0.75, -1.00, 1
    ),
}

@dataclass(frozen=True)
class RelationshipObservation:
    """Carry one categorical observation with explicit Artifact and Source evidence.

    携带一条有明确 Artifact 和 Source 证据的分类观察。
    """
    artifact_id: str
    subject_id: str
    reason: RelationshipReason
    strength: RelationshipStrength
    confidence: float
    source_ids: tuple[str, ...]
    scope: ConversationScope


@dataclass(frozen=True)
class RelationshipScoringPolicy:
    """Hold resolved scoring settings; parse configuration outside core.

    保存已解析评分设置，在 core 外解析配置。
    """

    version: str = RELATIONSHIP_POLICY_VERSION
    learning_rate: float = 0.25
    max_revision_delta: float = 0.10
    minimum_evidence_confidence: float = 0.60
    private_weight: float = 1.0
    group_weight: float = 0.5
    unknown_weight: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("relationship policy version is required")
        for name in (
            "learning_rate",
            "max_revision_delta",
            "minimum_evidence_confidence",
            "private_weight",
            "group_weight",
            "unknown_weight",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")


@dataclass(frozen=True)
class ScoredRelationshipEvidence:
    """Carry the derived signal, weighted target and evidence references.

    携带派生信号、加权目标及证据引用。
    """
    observation: RelationshipObservation
    signal: RelationshipSignal
    effective_target: float


@dataclass(frozen=True)
class RelationshipRevisionPlan:
    """Describe one bounded relationship revision and reviewed evidence; no persistence.

    描述一次有界关系修订及已审证据，不执行保存。
    """
    target: float
    delta: float
    affinity: float
    confidence: float
    evidence_count: int
    band: RelationshipBand
    counted_artifact_ids: tuple[str, ...]
    reviewed_artifact_ids: tuple[str, ...]
    counted_source_ids: tuple[str, ...]


def score_observation(
    observation: RelationshipObservation,
    policy: RelationshipScoringPolicy = RelationshipScoringPolicy(),
) -> ScoredRelationshipEvidence:
    """Derive a signal and scope-weighted target from one categorical observation.

    根据一条分类观察推导信号及范围加权目标。
    """
    try:
        reason = RelationshipReason(observation.reason)
        strength = RelationshipStrength(observation.strength)
        scope = ConversationScope(observation.scope)
    except ValueError as exc:
        raise ValueError("invalid relationship observation vocabulary") from exc
    confidence = _bounded_confidence(observation.confidence)
    if not str(observation.artifact_id or "").strip():
        raise ValueError("relationship observation artifact_id is required")
    if not str(observation.subject_id or "").strip():
        raise ValueError("relationship observation subject_id is required")
    if not observation.source_ids or any(
        not str(source_id or "").strip() for source_id in observation.source_ids
    ):
        raise ValueError("relationship observation source_ids are required")
    rule = EVIDENCE_RULES[reason]
    target = (
        rule.mild_target
        if strength is RelationshipStrength.MILD
        else rule.strong_target
    )
    weight = {
        ConversationScope.PRIVATE: policy.private_weight,
        ConversationScope.GROUP: policy.group_weight,
        ConversationScope.UNKNOWN: policy.unknown_weight,
    }[scope]
    normalized = RelationshipObservation(
        artifact_id=str(observation.artifact_id),
        subject_id=str(observation.subject_id),
        reason=reason,
        strength=strength,
        confidence=confidence,
        source_ids=tuple(dict.fromkeys(str(value) for value in observation.source_ids)),
        scope=scope,
    )
    return ScoredRelationshipEvidence(normalized, rule.signal, target * weight)


def plan_relationship_revision(
    current: RelationshipSnapshot,
    observations: Iterable[RelationshipObservation],
    policy: RelationshipScoringPolicy = RelationshipScoringPolicy(),
    *,
    previously_reviewed_artifact_ids: Iterable[str] = (),
    created_by_artifact_id: Mapping[str, str] | None = None,
) -> RelationshipRevisionPlan | None:
    """Plan one bounded revision from fresh valid evidence, accounting for capped reviewed rows.

    根据新鲜有效证据计划一次有界修订，并计入达到上限的已审行。
    """
    previously_reviewed = {
        str(value) for value in previously_reviewed_artifact_ids if str(value)
    }
    scored: list[ScoredRelationshipEvidence] = []
    for observation in observations:
        if str(observation.artifact_id or "") in previously_reviewed:
            continue
        try:
            evidence = score_observation(observation, policy)
        except (TypeError, ValueError):
            continue
        if evidence.observation.subject_id != current.subject_id:
            continue
        if evidence.observation.confidence < policy.minimum_evidence_confidence:
            continue
        scored.append(evidence)
    created = created_by_artifact_id or {}
    scored.sort(
        key=lambda evidence: (
            str(created.get(evidence.observation.artifact_id, "")),
            evidence.observation.artifact_id,
        )
    )
    if not scored:
        return None

    reviewed_ids = tuple(item.observation.artifact_id for item in scored)
    per_reason: dict[RelationshipReason, int] = {}
    counted: list[ScoredRelationshipEvidence] = []
    for evidence in scored:
        reason = evidence.observation.reason
        seen = per_reason.get(reason, 0)
        if seen >= EVIDENCE_RULES[reason].max_per_cycle:
            continue
        per_reason[reason] = seen + 1
        counted.append(evidence)
    if not counted:
        return None

    total_confidence = sum(item.observation.confidence for item in counted)
    target = sum(
        item.effective_target * item.observation.confidence for item in counted
    ) / total_confidence
    raw_delta = policy.learning_rate * (target - current.affinity)
    delta = max(-policy.max_revision_delta, min(policy.max_revision_delta, raw_delta))
    affinity = max(-1.0, min(1.0, current.affinity + delta))
    evidence_count = current.evidence_count + len(counted)
    confidence = evidence_count / (evidence_count + _CONFIDENCE_PRIOR_COUNT)
    positive = any(
        item.signal in (RelationshipSignal.POSITIVE, RelationshipSignal.REPAIR)
        for item in counted
    )
    band = band_for(
        affinity,
        confidence,
        previous=current.band,
        positive_evidence=positive,
    )
    counted_ids = tuple(item.observation.artifact_id for item in counted)
    counted_sources = tuple(dict.fromkeys(
        source_id
        for item in counted
        for source_id in item.observation.source_ids
    ))
    return RelationshipRevisionPlan(
        target=target,
        delta=delta,
        affinity=affinity,
        confidence=confidence,
        evidence_count=evidence_count,
        band=band,
        counted_artifact_ids=counted_ids,
        reviewed_artifact_ids=reviewed_ids,
        counted_source_ids=counted_sources,
    )


def _bounded_confidence(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("relationship evidence confidence must be numeric")
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("relationship evidence confidence must be numeric") from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise ValueError("relationship evidence confidence must be within [0, 1]")
    return confidence
