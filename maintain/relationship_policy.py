"""Prepare relationship replacement content and validate supplied scope/confidence values.

准备关系替换内容并校验给定范围及置信度值，不执行读写。
"""

from __future__ import annotations

import math

try:
    from .ports import ArtifactCache, ArtifactStore, SourceStore
    from ..core.domain.memory.artifact import Artifact, Lineage, make, revise, validate
    from ..core.domain.social.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from ..core.domain.social.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )
except ImportError:
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore
    from core.domain.memory.artifact import Artifact, Lineage, make, revise, validate
    from core.domain.social.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from core.domain.social.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )

def _replacement(
    existing: Artifact | None,
    subject_id: str,
    plan,
    policy: RelationshipScoringPolicy,
) -> Artifact:
    """Prepare existing relationship payload and lineage from the pure core plan / 根据纯内核计划准备既有关系内容及来源。"""
    payload = {
        "summary": summary_for(plan.band),
        "affinity": round(plan.affinity, 6),
        "confidence": round(plan.confidence, 6),
        "evidence_count": plan.evidence_count,
        "relation_band": plan.band.value,
        "policy": {
            "version": policy.version,
            "private_weight": policy.private_weight,
            "group_weight": policy.group_weight,
            "learning_rate": policy.learning_rate,
            "max_revision_delta": policy.max_revision_delta,
        },
    }
    old_sources = existing.header.lineage.sources if existing else ()
    old_derived = existing.header.lineage.derived_from if existing else ()
    lineage = Lineage(
        sources=tuple(dict.fromkeys((*old_sources, *plan.counted_source_ids))),
        derived_from=tuple(dict.fromkeys((
            *old_derived, *plan.reviewed_artifact_ids,
        ))),
    )
    if existing is not None:
        return revise(existing, payload=payload, lineage=lineage)
    return make(
        "relationship",
        payload,
        id=relationship_id(subject_id),
        subject_id=subject_id,
        scope="private",
        said_by="inferred",
        shareable="private_only",
        lineage=lineage,
    )


def _scope_of(session_id: str) -> ConversationScope:
    """Classify the supplied session using existing private/group/unknown markers / 按既有私聊、群聊或未知标记分类给定会话。"""
    value = str(session_id or "")
    if ":FriendMessage:" in value:
        return ConversationScope.PRIVATE
    if ":GroupMessage:" in value:
        return ConversationScope.GROUP
    return ConversationScope.UNKNOWN


def _confidence(art: Artifact) -> float:
    """Validate a finite confidence in the existing accepted range / 校验既有允许范围内的有限置信度。"""
    value = art.header.strength.confidence
    if isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return confidence if math.isfinite(confidence) and 0.0 <= confidence <= 1.0 else 0.0
