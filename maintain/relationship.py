"""Read verified observations, compute existing relationship plans and commit per subject.

读取已验证观察，计算既有关系计划并按主体分别提交。
"""

from __future__ import annotations

from .writer import MaintenanceWriter
from .plans import RevisionPlan, RevisionWrite

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

from .relationship_evidence import _RESERVED_SUBJECTS, _current_relationships, _validated_observations
from .relationship_policy import _replacement, _scope_of, _confidence


def consolidate_relationships(
    artifacts: ArtifactStore,
    sources: SourceStore,
    cache: ArtifactCache,
    policy: RelationshipScoringPolicy = RelationshipScoringPolicy(),
    *, writer: MaintenanceWriter | None = None,
) -> int:
    """Commit one existing relationship revision per subject with fresh verified evidence / 以新已验证证据按主体提交一个既有关系版本。"""
    writer = writer or MaintenanceWriter(artifacts, cache)
    writer.ensure_ready()
    current = _current_relationships(cache)
    candidates = _validated_observations(cache, sources, policy)
    made = 0
    for subject_id in sorted(candidates):
        existing = current.get(subject_id)
        if existing is False:
            continue
        snapshot = (
            snapshot_from_payload(
                existing.payload,
                subject_id=subject_id,
                artifact_id=existing.header.id,
                revision=existing.header.revision,
            )
            if isinstance(existing, Artifact)
            else RelationshipSnapshot(subject_id=subject_id)
        )
        previously_reviewed = (
            existing.header.lineage.derived_from
            if isinstance(existing, Artifact)
            else ()
        )
        observations = candidates[subject_id]
        created = {
            observation.artifact_id: artifact.header.time.created
            for observation, artifact in observations
        }
        plan = plan_relationship_revision(
            snapshot,
            (observation for observation, _artifact in observations),
            policy,
            previously_reviewed_artifact_ids=previously_reviewed,
            created_by_artifact_id=created,
        )
        if plan is None:
            continue
        replacement = _replacement(
            existing if isinstance(existing, Artifact) else None,
            subject_id,
            plan,
            policy,
        )
        validate(replacement)
        plan = RevisionPlan((RevisionWrite(
            replacement, existing.header.revision if isinstance(existing, Artifact) else 0,
            plan.counted_source_ids,
        ),), "revise" if isinstance(existing, Artifact) else "create", "relationship evidence consolidation")
        writer.execute(plan, grouped=False)
        current[subject_id] = replacement
        made += 1
    return made
