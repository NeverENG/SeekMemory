"""Relationship Artifact payload validation."""

from __future__ import annotations

import math
from typing import Any

from ..relationship import RELATIONSHIP_POLICY_VERSION, RelationshipBand

# Preserve the persisted vocabulary and order from its domain owner.
BANDS = tuple(band.value for band in RelationshipBand)


def _number(payload: dict[str, Any], key: str, low: float, high: float) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"relationship.{key} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"relationship.{key} must be numeric") from exc
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"relationship.{key} must be within [{low}, {high}]")
    return number


def validate(payload: dict[str, Any]) -> None:
    """Reject malformed or unbounded relationship snapshots."""
    _number(payload, "affinity", -1.0, 1.0)
    _number(payload, "confidence", 0.0, 1.0)
    count = payload.get("evidence_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("relationship.evidence_count must be a non-negative integer")
    band = payload.get("relation_band")
    if band not in BANDS:
        raise ValueError(f"relationship.relation_band must be one of {'|'.join(BANDS)}")
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("relationship.summary must be a non-empty string")
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("relationship.policy must be an object")
    if policy.get("version") != RELATIONSHIP_POLICY_VERSION:
        raise ValueError(f"relationship.policy.version must be {RELATIONSHIP_POLICY_VERSION}")
    for key in (
        "private_weight",
        "group_weight",
        "learning_rate",
        "max_revision_delta",
    ):
        _number(policy, key, 0.0, 1.0)
