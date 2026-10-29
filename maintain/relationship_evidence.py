"""Read relationship state and exact immutable observations without writing state.

读取关系状态及精确不可变观察，不写入状态。
"""

from __future__ import annotations

import math

try:
    from .ports import ArtifactCache, ArtifactStore, SourceStore
    from ..core.artifact import Artifact, Lineage, make, revise, validate
    from ..core.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from ..core.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )
except ImportError:
    from maintain.ports import ArtifactCache, ArtifactStore, SourceStore
    from core.artifact import Artifact, Lineage, make, revise, validate
    from core.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from core.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )

from .relationship_policy import _scope_of, _confidence

_RESERVED_SUBJECTS = {"", "self", "relation", "world"}


def _current_relationships(cache: ArtifactCache) -> dict[str, Artifact | bool]:
    """Read one valid existing relationship per subject; conflicting rows disable that subject / 按主体读取唯一有效已有关系，冲突行禁用该主体。"""
    grouped: dict[str, list[Artifact]] = {}
    for art in cache.active("relationship"):
        grouped.setdefault(str(art.header.subject_id or ""), []).append(art)
    out: dict[str, Artifact | bool] = {}
    for subject, rows in grouped.items():
        if subject in _RESERVED_SUBJECTS or len(rows) != 1:
            out[subject] = False
            continue
        art = rows[0]
        try:
            validate(art)
            snapshot_from_payload(
                art.payload,
                subject_id=subject,
                artifact_id=art.header.id,
                revision=art.header.revision,
            )
        except ValueError:
            out[subject] = False
            continue
        out[subject] = art
    return out


def _validated_observations(
    cache: ArtifactCache,
    sources: SourceStore,
    policy: RelationshipScoringPolicy,
) -> dict[str, list[tuple[RelationshipObservation, Artifact]]]:
    """Read exact immutable evidence and reject invalid subject/scope/confidence observations / 读取精确不可变证据并拒绝无效主体、范围或置信度观察。"""
    raw: list[tuple[Artifact, RelationshipReason, RelationshipStrength, float]] = []
    source_ids: list[str] = []
    for art in cache.active("memory"):
        subject = str(art.header.subject_id or "")
        if subject in _RESERVED_SUBJECTS or art.header.lineage.derived_from:
            continue
        if art.payload.get("relationship_policy_version") != RELATIONSHIP_POLICY_VERSION:
            continue
        try:
            reason = RelationshipReason(str(art.payload.get("relationship_reason") or ""))
            strength = RelationshipStrength(str(art.payload.get("relationship_strength") or ""))
        except ValueError:
            continue
        confidence = _confidence(art)
        if confidence < policy.minimum_evidence_confidence:
            continue
        ids = tuple(str(value) for value in art.header.lineage.sources if str(value))
        if not ids:
            continue
        raw.append((art, reason, strength, confidence))
        source_ids.extend(ids)

    originals = sources.sources_by_ids(list(dict.fromkeys(source_ids))) if source_ids else {}
    out: dict[str, list[tuple[RelationshipObservation, Artifact]]] = {}
    for art, reason, strength, confidence in raw:
        subject = str(art.header.subject_id or "")
        ids = tuple(str(value) for value in art.header.lineage.sources if str(value))
        rows = [originals.get(source_id) for source_id in ids]
        if any(row is None for row in rows):
            continue
        user_rows = [row for row in rows if row is not None and row.role == "user"]
        if not user_rows or any(row.speaker_id != subject for row in user_rows):
            continue
        scopes = {_scope_of(row.session_id) for row in rows if row is not None}
        if len(scopes) != 1:
            continue
        observation = RelationshipObservation(
            artifact_id=art.header.id,
            subject_id=subject,
            reason=reason,
            strength=strength,
            confidence=confidence,
            source_ids=ids,
            scope=next(iter(scopes)),
        )
        out.setdefault(subject, []).append((observation, art))
    return out
