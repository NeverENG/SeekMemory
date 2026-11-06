"""Validate evidence-oriented relationship observations without deriving scores or writing state.

校验面向证据的关系观察，不推导分数或写入状态。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

try:
    from ..app.contracts import ChatRequest
    from ..core.domain.social.relationship_rules import (
        ConversationScope, EVIDENCE_RULES, RelationshipCandidate, RelationshipReason, RelationshipStrength,
    )
    from ..core.domain.memory.source import Source
except ImportError:
    from app.contracts import ChatRequest
    from core.domain.social.relationship_rules import (
        ConversationScope, EVIDENCE_RULES, RelationshipCandidate, RelationshipReason, RelationshipStrength,
    )
    from core.domain.memory.source import Source

SEPARATOR = "\x1d"

_STOP_REQUEST = re.compile(
    r"\b(?:stop|quit|cease|enough|don't|do not|refrain)\b|(?:不要|别再?|停止|停下|够了|到此为止)",
    re.IGNORECASE,
)


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


@dataclass(frozen=True)
class RelationshipVerdict:
    status: str
    repair_of: str = ""


def _instant(value: object) -> datetime | None:
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return at.astimezone(timezone.utc) if at.tzinfo is not None and at.utcoffset() is not None else None


def _negative_prior(item: object, candidate: RelationshipCandidate, actor: Source) -> bool:
    reason = getattr(item, "reason", None)
    try:
        rule = EVIDENCE_RULES[RelationshipReason(reason)]
    except (KeyError, ValueError):
        return False
    at = _instant(getattr(item, "event_at", None))
    actor_at = _instant(actor.at)
    return (
        rule.signal.value in ("negative", "boundary_violation")
        and getattr(item, "subject_id", None) == candidate.subject_id
        and getattr(item, "status", "verified") == "verified"
        and bool(getattr(item, "event_id", ""))
        and at is not None and actor_at is not None and at < actor_at
    )


def _harassment_evidence(evidence: tuple[Source, ...], actor: Source, stop_id: object) -> bool:
    stop = next((source for source in evidence if source.id == stop_id), None)
    if stop is None or stop.role != "assistant" or stop.session_id != actor.session_id:
        return False
    if not _STOP_REQUEST.search(stop.text):
        return False
    stopped_at, actor_at = _instant(stop.at), _instant(actor.at)
    if stopped_at is None or actor_at is None or stopped_at >= actor_at:
        return False
    return any(
        source.role == "user" and source.speaker_id == actor.speaker_id
        and source.session_id == actor.session_id
        and (at := _instant(source.at)) is not None and at < stopped_at
        for source in evidence
    )


async def verify_relationship(candidate: RelationshipCandidate, evidence: tuple[Source, ...], model, prior_negative: tuple = ()) -> RelationshipVerdict:
    """Cross-check the model's semantic judgment against immutable Source evidence."""
    sources = {source.id: source for source in evidence}
    actor = sources.get(candidate.primary_source_id)
    if (
        actor is None or actor.role != "user" or actor.speaker_id != candidate.subject_id
        or candidate.scope is ConversationScope.UNKNOWN or _instant(actor.at) is None
        or actor.session_id != candidate.session_id or candidate.primary_source_id not in candidate.source_ids
        or len(sources) != len(evidence) or len(sources) != len(candidate.source_ids)
        or set(sources) != set(candidate.source_ids)
        or any(source.session_id != candidate.session_id for source in evidence)
        or any(source.role == "user" and source.speaker_id != candidate.subject_id for source in evidence)
    ):
        return RelationshipVerdict("abstain")

    eligible_priors = sorted(
        (item for item in prior_negative if _negative_prior(item, candidate, actor)),
        key=lambda item: (_instant(item.event_at), item.event_id),
        reverse=True,
    )[:3]
    response = await model.complete(ChatRequest(
        session_id=candidate.session_id, system_prompt=(
            "只返回一个 JSON 对象，字段 reason,source_ids,target,decision,repair_of,stop_source_id。"
            "decision 只能是 verified 或 abstain；target 只能是 assistant、other 或 unknown。"
            "只评估该用户直接对 assistant 的言行；引用他人、转述和针对第三方的言行必须 abstain。"
            "reason 必须符合全部 source_ids 的真实语义。repair 仅限该用户确实修复所列先前负面事件，"
            "repair_of 必须是列出的事件 ID；否则 abstain。harassment 仅限同一用户在 assistant "
            "明确要求停止后继续该行为，stop_source_id 必须是证据中 assistant 的停止请求 ID；否则 abstain。"
        ), prompt=json.dumps({
            "candidate": {
                "reason": candidate.reason.value, "subject_id": candidate.subject_id,
                "primary_source_id": candidate.primary_source_id,
                "source_ids": candidate.source_ids,
            },
            "sources": [
                {"id": source.id, "role": source.role, "speaker_id": source.speaker_id,
                 "text": source.text} for source in evidence
            ],
            "prior_negative": [
                {"event_id": item.event_id, "reason": RelationshipReason(item.reason).value}
                for item in eligible_priors
            ],
        }, ensure_ascii=False),
    ))
    parsed = json.loads(response.text)
    if not isinstance(parsed, dict) or parsed.get("decision") not in ("verified", "abstain"):
        raise ValueError("invalid relationship verdict")
    if parsed["decision"] == "abstain":
        return RelationshipVerdict("abstain")
    if (
        parsed.get("reason") != candidate.reason.value
        or not isinstance(parsed.get("source_ids"), list)
        or len(parsed["source_ids"]) != len(candidate.source_ids)
        or any(not isinstance(source_id, str) for source_id in parsed["source_ids"])
        or set(parsed["source_ids"]) != set(candidate.source_ids)
        or parsed.get("target") != "assistant"
    ):
        return RelationshipVerdict("abstain")
    repair_id = parsed.get("repair_of") or ""
    if candidate.reason == RelationshipReason.REPAIR:
        if not isinstance(repair_id, str) or not any(
            item.event_id == repair_id for item in eligible_priors
        ):
            return RelationshipVerdict("abstain")
    elif repair_id:
        return RelationshipVerdict("abstain")
    if candidate.reason == RelationshipReason.HARASSMENT:
        if not _harassment_evidence(evidence, actor, parsed.get("stop_source_id")):
            return RelationshipVerdict("abstain")
    elif parsed.get("stop_source_id"):
        return RelationshipVerdict("abstain")
    return RelationshipVerdict("verified", repair_id)
