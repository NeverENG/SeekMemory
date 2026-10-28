"""Pure persistent relationship snapshots and band transitions."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

# Persisted policy identity; consumers must import this definition.
RELATIONSHIP_POLICY_VERSION = "relationship-v1"

# Internal confidence and affinity thresholds, separate from configurable weights.
HARD_GATE_CONFIDENCE = 0.60
_DISLIKE_ENTRY = -0.50
_DISLIKE_EXIT = -0.25
_LOW_ENTRY = -0.20
_LOW_EXIT = -0.10
_CLOSE_ENTRY = 0.60
_CLOSE_EXIT = 0.50
_WARM_ENTRY = 0.20
_WARM_EXIT = 0.10


class RelationshipBand(str, Enum):
    """Persisted band vocabulary shared by decisions and payload validation."""

    CLOSE = "close"
    WARM = "warm"
    NEUTRAL = "neutral"
    LOW = "low"
    DISLIKE = "dislike"



@dataclass(frozen=True)
class RelationshipSnapshot:
    subject_id: str = ""
    affinity: float = 0.0
    confidence: float = 0.0
    evidence_count: int = 0
    band: RelationshipBand = RelationshipBand.NEUTRAL
    artifact_id: str = ""
    revision: int = 0




def relationship_id(subject_id: str) -> str:
    """Return a stable opaque Artifact id for one global person relationship."""
    subject = str(subject_id or "").strip()
    if not subject:
        raise ValueError("relationship subject_id is required")
    digest = hashlib.sha256(subject.encode("utf-8")).hexdigest()[:24]
    return f"relationship_{digest}"


def summary_for(band: RelationshipBand) -> str:
    return {
        RelationshipBand.CLOSE: "关系状态：亲近",
        RelationshipBand.WARM: "关系状态：温暖",
        RelationshipBand.NEUTRAL: "关系状态：中性",
        RelationshipBand.LOW: "关系状态：冷淡",
        RelationshipBand.DISLIKE: "关系状态：不喜欢",
    }[band]


def band_for(
    affinity: float,
    confidence: float,
    *,
    previous: RelationshipBand = RelationshipBand.NEUTRAL,
    positive_evidence: bool = False,
) -> RelationshipBand:
    """Classify a bounded affinity using hysteresis around stable bands."""
    value = float(affinity)
    certainty = float(confidence)
    if not math.isfinite(value) or not math.isfinite(certainty):
        raise ValueError("relationship values must be finite")
    if not -1.0 <= value <= 1.0 or not 0.0 <= certainty <= 1.0:
        raise ValueError("relationship values are outside their bounds")

    if previous is RelationshipBand.DISLIKE:
        if value <= _DISLIKE_EXIT or not positive_evidence:
            return RelationshipBand.DISLIKE
    if value <= _DISLIKE_ENTRY and certainty >= HARD_GATE_CONFIDENCE:
        return RelationshipBand.DISLIKE
    if previous is RelationshipBand.LOW and value < _LOW_EXIT:
        return RelationshipBand.LOW
    if value <= _LOW_ENTRY:
        return RelationshipBand.LOW
    if previous is RelationshipBand.CLOSE and value >= _CLOSE_EXIT:
        return RelationshipBand.CLOSE
    if value >= _CLOSE_ENTRY and certainty >= HARD_GATE_CONFIDENCE:
        return RelationshipBand.CLOSE
    if previous is RelationshipBand.WARM and value >= _WARM_EXIT:
        return RelationshipBand.WARM
    if value >= _WARM_ENTRY:
        return RelationshipBand.WARM
    return RelationshipBand.NEUTRAL


def snapshot_from_payload(
    payload: Mapping[str, Any],
    *,
    subject_id: str,
    artifact_id: str,
    revision: int,
) -> RelationshipSnapshot:
    """Build a validated runtime snapshot from an Artifact payload."""
    if not isinstance(payload, Mapping):
        raise ValueError("relationship payload must be a mapping")
    affinity = _finite(payload.get("affinity"), -1.0, 1.0, "affinity")
    confidence = _finite(payload.get("confidence"), 0.0, 1.0, "confidence")
    count = payload.get("evidence_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("evidence_count must be a non-negative integer")
    try:
        band = RelationshipBand(str(payload.get("relation_band") or ""))
    except ValueError as exc:
        raise ValueError("unknown relationship band") from exc
    return RelationshipSnapshot(
        str(subject_id or ""), affinity, confidence, count, band,
        str(artifact_id or ""), max(0, int(revision)),
    )




def _finite(value: object, low: float, high: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{name} is outside its bounds")
    return number
