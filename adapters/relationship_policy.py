"""Read-only V2 relationship lookup; never affect runtime replies or prompts."""

from __future__ import annotations

try:
    from ..app.ports import ArtifactCache
    from ..core.domain.memory.artifact import validate
    from ..core.domain.social.relationship import RelationshipSnapshot, snapshot_from_payload
except ImportError:
    from app.ports import ArtifactCache
    from core.domain.memory.artifact import validate
    from core.domain.social.relationship import RelationshipSnapshot, snapshot_from_payload


class RelationshipReader:
    """Read a unique active V2 relationship; malformed or V1 rows stay neutral."""

    def __init__(self, cache: ArtifactCache | None) -> None:
        self.cache = cache

    def get(self, subject_id: str) -> RelationshipSnapshot:
        """Return a content-free snapshot, failing open for invalid or missing rows."""
        subject = str(subject_id or "").strip()
        neutral = RelationshipSnapshot(subject_id=subject)
        if not subject or self.cache is None:
            return neutral
        try:
            rows = [
                art for art in self.cache.by_subject(subject)
                if art.header.family == "relationship" and art.header.state == "active"
            ]
            if len(rows) != 1:
                return neutral
            art = rows[0]
            validate(art)
            return snapshot_from_payload(
                art.payload, subject_id=subject, artifact_id=art.header.id,
                revision=art.header.revision,
            )
        except Exception:  # Corrupt relationship data must not affect ordinary replies.
            return neutral
