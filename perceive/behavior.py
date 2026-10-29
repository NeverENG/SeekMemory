"""Validate paired assistant behavior and prepare payloads without I/O.

校验有配对的助手行为并准备内容，不执行读写。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

try:
    from ..core.bot_behavior import BEHAVIORS
except ImportError:
    from core.bot_behavior import BEHAVIORS

BEHAVIOR_FIELD = "bot_behavior"
EVIDENCE_FIELD = "evidence_source_ids"
BEHAVIOR_TEXT_FIELDS = ("bot_action", "bot_tone", "bot_boundary", "outcome")

# Exactly six categories are allowed / 仅允许六个类别，其他值构造失败。

# Missing behavior confidence stays below 0.9 / 行为缺失置信度时保持低于 0.9。
DEFAULT_BEHAVIOR_CONFIDENCE = 0.6

_SEPARATOR = "\x1e"
_ID_SEPARATOR = "|"


def behavior_of(payload: Mapping[str, Any] | None) -> str:
    """Read the declared bot behavior category / 读取声明的机器人行为类别。"""
    if not isinstance(payload, Mapping):
        return ""
    value = str(payload.get(BEHAVIOR_FIELD) or "").strip()
    return value if value in BEHAVIORS else ""


def is_behavior(payload: Mapping[str, Any] | None) -> bool:
    """Recognize the existing bot behavior payload form / 识别既有机器人行为内容形式。"""
    return bool(behavior_of(payload))


def check_payload(payload: Mapping[str, Any] | None) -> None:
    """Validate the supported behavior payload shape / 校验受支持的行为内容结构。"""
    if not isinstance(payload, Mapping):
        raise ValueError("memory payload must be a mapping")
    raw = payload.get(BEHAVIOR_FIELD)
    if raw not in (None, ""):
        if str(raw).strip() not in BEHAVIORS:
            raise ValueError(f"unknown bot_behavior: {raw!r}")


def payload_of(item: Mapping[str, Any]) -> dict[str, Any]:
    """Prepare family payload without creating or persisting an Artifact / 准备类型内容，不创建或持久化记忆。"""
    out = {key: value for key, value in item.items() if key != EVIDENCE_FIELD}
    qualifies = is_behavior(out)
    for key in BEHAVIOR_TEXT_FIELDS:
        value = out.get(key)
        if not isinstance(value, str) or not value.strip():
            out.pop(key, None)
        else:
            out[key] = value.strip()
    if qualifies:
        out[BEHAVIOR_FIELD] = behavior_of(out)
    return out


def evidence_ids(payload: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Normalize supplied evidence IDs without inventing links / 规范化给定证据编号，不补造关联。"""
    if not isinstance(payload, Mapping):
        return ()
    raw = payload.get(EVIDENCE_FIELD)
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple, set)):
        return ()
    seen: list[str] = []
    for value in raw:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return tuple(seen)


def behavior_boundary(
    boundary: str, behavior: str, ids: tuple[str, ...] | list[str]
) -> str:
    """Extend deduplication identity with behavior category and exact evidence / 以行为类别及精确证据扩展去重身份。"""
    cleaned = sorted({str(value).strip() for value in ids or () if str(value).strip()})
    return f"{boundary}{_SEPARATOR}{behavior}{_SEPARATOR}{_ID_SEPARATOR.join(cleaned)}"


def is_behavior_key(key: str) -> bool:
    """Recognize an existing behavior deduplication key / 识别既有行为去重键。"""
    return _SEPARATOR in str(key or "")


def dedupe_behaviors(
    items: list[dict],
    *,
    existing_keys: set[str],
    boundary_of: Callable[[dict], str],
) -> list[dict]:
    """Keep distinct behavior/evidence observations in their supplied boundary / 在给定范围内保留不同的行为及证据观察。"""
    seen = set(existing_keys)
    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if is_behavior(item):
            key = boundary_of(item)
            if key in seen:
                continue
            seen.add(key)
        kept.append(item)
    return kept


def _session_of(turn: Any) -> str:
    return str(getattr(turn, "session_id", "") or "")


def _role_of(turn: Any) -> str:
    return str(getattr(turn, "role", "") or "")


def _reply_to_of(turn: Any) -> str:
    return str(getattr(turn, "reply_to", "") or "")


def validate_evidence(
    payload: Mapping[str, Any],
    available: Mapping[str, Any],
    *,
    session_id: str = "",
) -> tuple[str, ...]:
    """Validate exact cited evidence and user/assistant pairing in one session / 在同一会话中校验精确引用的证据及用户与助手配对。"""
    ids = evidence_ids(payload)
    if not ids:
        if is_behavior(payload):
            raise ValueError("bot_behavior item requires evidence_source_ids")
        return ()
    unknown = [value for value in ids if value not in available]
    if unknown:
        raise ValueError("evidence_source_ids not in this batch")
    sessions = {_session_of(available[value]) for value in ids}
    if session_id:
        if any(value != session_id for value in sessions):
            raise ValueError("evidence_source_ids cross session")
    elif len(sessions) > 1:
        raise ValueError("evidence_source_ids cross session")
    if not is_behavior(payload):
        return ids
    if len(ids) != 2:
        raise ValueError("behavior evidence must identify one user/reply pair")
    for value in ids:
        assistant = available[value]
        if _role_of(assistant) != "assistant":
            continue
        parent_id = _reply_to_of(assistant)
        parent = available.get(parent_id) if parent_id else None
        if parent is None or _role_of(parent) != "user":
            continue
        if _session_of(parent) != _session_of(assistant):
            continue
        if parent_id in ids:
            return ids
    raise ValueError("bot_behavior item requires an assistant turn and its user parent")
