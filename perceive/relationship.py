"""Validate evidence-oriented relationship observations without deriving scores or writing state.

校验面向证据的关系观察，不推导分数或写入状态。
"""

from __future__ import annotations

from typing import Any, Mapping

try:
    from ..core.domain.social.relationship_rules import (
        EVIDENCE_RULES,
        RelationshipReason,
        RelationshipStrength,
    )
except ImportError:
    from core.domain.social.relationship_rules import (
        EVIDENCE_RULES,
        RelationshipReason,
        RelationshipStrength,
    )

SEPARATOR = "\x1d"


def reason_of(payload: Mapping[str, Any] | None) -> RelationshipReason | None:
    """Read the declared relationship reason code / 读取声明的关系原因码。"""
    if not isinstance(payload, Mapping):
        return None
    try:
        return RelationshipReason(str(payload.get("relationship_reason") or "").strip())
    except ValueError:
        return None


def signal_of(payload: Mapping[str, Any] | None) -> str:
    """Derive the existing relationship signal from its allowed reason / 根据允许的原因推导既有关系信号。"""
    reason = reason_of(payload)
    return EVIDENCE_RULES[reason].signal.value if reason is not None else ""


def is_relationship_observation(payload: Mapping[str, Any] | None) -> bool:
    """Recognize relationship observation payloads / 识别关系观察内容。"""
    return reason_of(payload) is not None


def validate_observation(payload: Mapping[str, Any] | None) -> None:
    """Reject unsupported relationship claims or fields / 拒绝不受支持的关系声明或字段。"""
    if not isinstance(payload, Mapping):
        raise ValueError("memory payload must be a mapping")
    if payload.get("relationship_signal") not in (None, ""):
        raise ValueError("relationship_signal is program-derived")
    raw_reason = payload.get("relationship_reason")
    raw_strength = payload.get("relationship_strength")
    if raw_reason in (None, "") and raw_strength in (None, ""):
        return
    try:
        RelationshipReason(str(raw_reason or "").strip())
    except ValueError as exc:
        raise ValueError(f"unknown relationship_reason: {raw_reason!r}") from exc
    try:
        RelationshipStrength(str(raw_strength or "").strip())
    except ValueError as exc:
        raise ValueError(f"unknown relationship_strength: {raw_strength!r}") from exc
    if str(payload.get("about") or "") != "relation":
        raise ValueError("relationship observation requires about=relation")


def observation_boundary(
    boundary: str,
    payload: Mapping[str, Any],
    evidence_ids: tuple[str, ...] | list[str],
) -> str:
    """Build the existing relationship/evidence deduplication identity / 构造既有关系及证据去重身份。"""
    reason = reason_of(payload)
    evidence = "|".join(str(value) for value in evidence_ids if str(value))
    return f"{boundary}{SEPARATOR}{reason.value if reason else ''}{SEPARATOR}{evidence}"
