"""Pure replayable relationship snapshots; no interaction or storage decisions."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Mapping

RELATIONSHIP_POLICY_VERSION = "relationship-v2"
SUMMARY = "关系状态：观察中"


@dataclass(frozen=True)
class RelationshipSnapshot:
    """Carry a content-free, six-dimensional observe-only relationship view."""

    subject_id: str = ""
    familiarity: float = 0.0
    trust: float = 0.0
    warmth: float = 0.0
    tension: float = 0.0
    stability: float = 0.0
    confidence: float = 0.0
    evidence_count: int = 0
    last_evidence_at: str = ""
    evaluated_at: str = ""
    artifact_id: str = ""
    revision: int = 0


def relationship_id(subject_id: str) -> str:
    """Return the stable opaque Artifact ID for one person's relationship."""
    subject = str(subject_id or "").strip()
    if not subject:
        raise ValueError("relationship subject_id is required")
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
    return f"relationship_{digest}"


def snapshot_from_payload(
    payload: Mapping[str, Any], *, subject_id: str, artifact_id: str, revision: int,
) -> RelationshipSnapshot:
    """Read only valid V2 dimensions; V1 or malformed data cannot affect the view."""
    if not isinstance(payload, Mapping):
        raise ValueError("relationship payload must be a mapping")
    policy = payload.get("policy")
    if not isinstance(policy, Mapping) or policy.get("version") != RELATIONSHIP_POLICY_VERSION:
        raise ValueError("relationship-v2 policy required")
    bounds = {
        "familiarity": (0.0, 1.0), "trust": (-1.0, 1.0),
        "warmth": (-1.0, 1.0), "tension": (0.0, 1.0),
        "stability": (0.0, 1.0), "confidence": (0.0, 1.0),
    }
    values: dict[str, float] = {}
    for name, (low, high) in bounds.items():
        raw = payload.get(name)
        if isinstance(raw, bool):
            raise ValueError(f"invalid relationship {name}")
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid relationship {name}") from exc
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"invalid relationship {name}")
        values[name] = value
    count = payload.get("evidence_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("invalid relationship evidence_count")
    last_at, evaluated_at = payload.get("last_evidence_at"), payload.get("evaluated_at")
    if not isinstance(last_at, str) or not isinstance(evaluated_at, str):
        raise ValueError("invalid relationship timestamps")
    return RelationshipSnapshot(
        subject_id=str(subject_id or ""), **values, evidence_count=count,
        last_evidence_at=last_at, evaluated_at=evaluated_at,
        artifact_id=str(artifact_id or ""), revision=revision,
    )
