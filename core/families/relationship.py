"""Validate V2 relationship payloads and preserved V1 history without I/O."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from ..domain.social.relationship import RELATIONSHIP_POLICY_VERSION, SUMMARY

_V1_BANDS = ("close", "warm", "neutral", "low", "dislike")


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
    """Validate active V2 snapshots while allowing historical V1 versions to load."""
    policy = payload.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("relationship.policy must be an object")
    version = policy.get("version")
    if version == "relationship-v1":
        _number(payload, "affinity", -1.0, 1.0)
        _number(payload, "confidence", 0.0, 1.0)
        count = payload.get("evidence_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("relationship.evidence_count must be a non-negative integer")
        if payload.get("relation_band") not in _V1_BANDS:
            raise ValueError("invalid relationship.relation_band")
        if not isinstance(payload.get("summary"), str) or not payload["summary"].strip():
            raise ValueError("relationship.summary must be a non-empty string")
        for key in ("private_weight", "group_weight", "learning_rate", "max_revision_delta"):
            _number(policy, key, 0.0, 1.0)
        return
    if version != RELATIONSHIP_POLICY_VERSION:
        raise ValueError("unsupported relationship policy")
    for key in ("familiarity", "tension", "stability", "confidence"):
        _number(payload, key, 0.0, 1.0)
    for key in ("trust", "warmth"):
        _number(payload, key, -1.0, 1.0)
    count = payload.get("evidence_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("relationship.evidence_count must be a non-negative integer")
    if payload.get("summary") != SUMMARY:
        raise ValueError("relationship summary is fixed during observation")
    for key in ("last_evidence_at", "evaluated_at"):
        value = payload.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"relationship.{key} requires a timezone-aware instant")
        try:
            when = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"relationship.{key} requires a timezone-aware instant") from exc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError(f"relationship.{key} requires a timezone-aware instant")
