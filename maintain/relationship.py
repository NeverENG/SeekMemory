"""Replay verified relationship evidence into versioned, observe-only Artifacts."""

from __future__ import annotations

import datetime
import json
from dataclasses import asdict

from .plans import RevisionPlan, RevisionWrite
from .ports import ArtifactCache, ArtifactStore, SourceStore
from .writer import MaintenanceWriter

try:
    from ..app.ports import RelationshipEventStore
    from ..core.domain.memory.artifact import Lineage, make, revise, validate
    from ..core.domain.social.relationship import RELATIONSHIP_POLICY_VERSION, SUMMARY, relationship_id
    from ..core.domain.social.relationship_rules import (
        ConversationScope, RelationshipCandidate, RelationshipReason,
        RelationshipScoringPolicy, RelationshipStrength, VERIFIER_VERSION,
        VerifiedRelationshipEvent, project_relationship, relationship_event_id,
    )
except ImportError:
    from app.ports import RelationshipEventStore
    from core.domain.memory.artifact import Lineage, make, revise, validate
    from core.domain.social.relationship import RELATIONSHIP_POLICY_VERSION, SUMMARY, relationship_id
    from core.domain.social.relationship_rules import (
        ConversationScope, RelationshipCandidate, RelationshipReason,
        RelationshipScoringPolicy, RelationshipStrength, VERIFIER_VERSION,
        VerifiedRelationshipEvent, project_relationship, relationship_event_id,
    )

_RESERVED_SUBJECTS = {"", "self", "relation", "world"}


def _scope_of(session_id: str) -> ConversationScope:
    if ":FriendMessage:" in session_id:
        return ConversationScope.PRIVATE
    if ":GroupMessage:" in session_id:
        return ConversationScope.GROUP
    return ConversationScope.UNKNOWN


def _event_from_row(row, sources: SourceStore) -> VerifiedRelationshipEvent | None:
    """Recheck immutable identity, session and timezone before replaying a verdict."""
    if (row.subject_id in _RESERVED_SUBJECTS or not row.event_id or not row.source_ids
        or any(not isinstance(source_id, str) or not source_id for source_id in row.source_ids)
        or len(row.source_ids) != len(set(row.source_ids))
        or row.primary_source_id not in row.source_ids):
        return None
    try:
        reason = RelationshipReason(row.reason)
        strength = RelationshipStrength(row.strength)
        scope = ConversationScope(row.scope)
        when = datetime.datetime.fromisoformat(row.event_at)
    except (TypeError, ValueError):
        return None
    if scope is ConversationScope.UNKNOWN or when.tzinfo is None or when.utcoffset() is None:
        return None
    loaded = sources.sources_by_ids(list(row.source_ids))
    primary = loaded.get(row.primary_source_id)
    if (primary is None or primary.id != row.primary_source_id or primary.role != "user"
        or primary.speaker_id != row.subject_id or primary.at != row.event_at
        or _scope_of(primary.session_id) is not scope):
        return None
    if any(
        (source := loaded.get(source_id)) is None or source.id != source_id
        or source.session_id != primary.session_id or _scope_of(source.session_id) is not scope
        or (source.role == "user" and source.speaker_id != row.subject_id)
        for source_id in row.source_ids
    ):
        return None
    return VerifiedRelationshipEvent(
        row.event_id, row.subject_id, reason, strength, scope, when,
        row.primary_source_id, row.source_ids, row.repair_of,
    )


def consolidate_relationships(
    artifacts: ArtifactStore,
    sources: SourceStore,
    relationship_events: RelationshipEventStore | None,
    cache: ArtifactCache | None,
    policy: RelationshipScoringPolicy | None = None,
    *,
    as_of: datetime.datetime | None = None,
    writer: MaintenanceWriter | None = None,
) -> int:
    """Commit changed V2 subjects with CAS and exact verified Source evidence."""
    if relationship_events is None or cache is None:
        return 0
    if writer is not None:
        writer.ensure_ready()
    policy = policy or RelationshipScoringPolicy()
    as_of = as_of or datetime.datetime.now(datetime.timezone.utc)
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("relationship projection requires a timezone")
    made = 0
    for subject in relationship_events.subjects(policy.verifier_version):
        if subject in _RESERVED_SUBJECTS:
            continue
        rows = tuple(row for row in relationship_events.by_subject(subject, policy.verifier_version)
                     if row.status == "verified")
        validated = tuple(
            (row, event) for row in rows if row.subject_id == subject
            if (event := _event_from_row(row, sources)) is not None and event.event_at <= as_of
        )
        if not validated:
            continue
        verified = tuple(event for _, event in validated)
        snapshot = project_relationship(verified, as_of, policy)
        if not snapshot.evidence_count:
            continue
        source_ids = tuple(dict.fromkeys(
            source_id for event in verified for source_id in event.source_ids
        ))
        origins = tuple(dict.fromkeys(
            row.origin_artifact_id for row, _ in validated
            if row.origin_artifact_id
            and (origin := artifacts.get(row.origin_artifact_id)) is not None
            and origin.header.family == "memory" and origin.header.subject_id == subject
        ))
        payload = {
            "summary": SUMMARY,
            **{key: getattr(snapshot, key) for key in (
                "familiarity", "trust", "warmth", "tension", "stability", "confidence",
                "evidence_count", "last_evidence_at", "evaluated_at",
            )},
            "policy": asdict(policy),
        }
        lineage = Lineage(sources=source_ids, derived_from=origins)
        node_id = relationship_id(subject)
        if any(art.header.family == "relationship" and art.header.id != node_id
               for art in cache.by_subject(subject)):
            continue  # Never create a competing head beside a legacy relationship ID.
        existing = artifacts.get(node_id)
        if existing is not None and (
            existing.header.family != "relationship" or existing.header.subject_id != subject
            or existing.header.state != "active"
        ):
            continue  # Never overwrite another identity or reactivate a disabled relationship.
        if existing is not None and existing.payload == payload and existing.header.lineage == lineage:
            continue
        replacement = (
            revise(existing, payload=payload, lineage=lineage) if existing is not None
            else make("relationship", payload, id=node_id, subject_id=subject,
                      scope="private", said_by="inferred", shareable="private_only", lineage=lineage)
        )
        validate(replacement)
        expected_revision = existing.header.revision if existing is not None else 0
        op = "revise" if existing is not None else "create"
        if writer is not None:
            writer.execute(RevisionPlan((RevisionWrite(
                replacement, expected_revision, source_ids,
            ),), op, RELATIONSHIP_POLICY_VERSION), grouped=False)
        else:
            artifacts.commit(
                replacement, expected_revision=expected_revision, op=op,
                reason=RELATIONSHIP_POLICY_VERSION, source_ids=source_ids,
            )
            cache.put(replacement)
        made += 1
    return made


def migrate_v1_candidates(
    artifacts: ArtifactStore, sources: SourceStore, relationship_events: RelationshipEventStore,
) -> int:
    """Queue attributable V1 memory versions without trusting historic scores."""
    queued = 0
    for art in artifacts.list("memory"):
        subject = str(art.header.subject_id or "")
        if subject in _RESERVED_SUBJECTS:
            continue
        known = {row.event_id for row in relationship_events.by_subject(subject, VERIFIER_VERSION)}
        # Version rows retain their original payload and header, including Source lineage.
        for version in reversed(artifacts.inspect_record(art.header.id).get("versions", [])):
            try:
                payload = json.loads(version["content"])
                header = json.loads(version["header"])
                if not isinstance(header, dict):
                    continue
                lineage = json.loads(header["lineage"])
                if (not isinstance(payload, dict) or not isinstance(lineage, dict)
                    or payload.get("relationship_policy_version") != "relationship-v1"
                    or header.get("subject_id") != subject or lineage.get("derived_from")):
                    continue
                reason = RelationshipReason(payload["relationship_reason"])
                strength = RelationshipStrength(payload["relationship_strength"])
                raw_ids = lineage.get("sources")
                if (not isinstance(raw_ids, list) or not raw_ids
                    or any(not isinstance(source_id, str) or not source_id for source_id in raw_ids)):
                    continue
                ids = tuple(raw_ids)
                if len(ids) != len(set(ids)):
                    continue
                loaded = sources.sources_by_ids(list(ids))
                if any(source_id not in loaded or loaded[source_id].id != source_id for source_id in ids):
                    continue
                users = [loaded[source_id] for source_id in ids if loaded[source_id].role == "user"]
                if reason is RelationshipReason.HARASSMENT:
                    if len(users) < 2:
                        continue
                    primary = max(users, key=lambda source: (source.at, source.id))
                elif len(users) == 1:
                    primary = users[0]
                else:
                    continue
                when = datetime.datetime.fromisoformat(primary.at)
                scope = _scope_of(primary.session_id)
                if (primary.speaker_id != subject or when.tzinfo is None
                    or when.utcoffset() is None or scope is ConversationScope.UNKNOWN
                    or any(row.session_id != primary.session_id or
                           (row.role == "user" and row.speaker_id != subject)
                           for row in loaded.values())):
                    continue
                candidate = RelationshipCandidate(
                    subject, reason, strength, primary.id, ids,
                    primary.session_id, scope, art.header.id, int(version["revision"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            event_id = relationship_event_id(candidate)
            if event_id in known:
                continue
            relationship_events.record_pending({
                "event_id": event_id, "verifier_version": VERIFIER_VERSION,
                "subject_id": subject, "reason": reason.value, "strength": strength.value,
                "scope": scope.value, "event_at": primary.at,
                "primary_source_id": primary.id, "source_ids": ids,
                "origin_artifact_id": art.header.id, "origin_revision": candidate.origin_revision,
            })
            known.add(event_id)
            queued += 1
    return queued
