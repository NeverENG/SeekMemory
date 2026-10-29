"""Pure topic continuity and legacy timestamp parsing; no queue or file access.

纯话题连续性及旧时间解析，不读取队列或文件；既有阈值和时间行为不变。
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

try:
    from ..app.contracts import DialogueTurn
except ImportError:
    from app.contracts import DialogueTurn

TOPIC_GAP_SECONDS = 5400
TOPIC_SIMILARITY = 0.12
TOPIC_TTL_SECONDS = 86400


def _parse_at(value: str) -> datetime | None:
    """Parse a legacy ISO timestamp without conversion / 解析旧 ISO 时间戳，不作转换。"""
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _bigrams(text: str) -> set[str]:
    """Build existing normalized character pairs; short input yields an empty set / 构造既有规范字符二元组，过短输入返回空集合。"""
    clean = "".join(ch.lower() for ch in str(text or "") if ch.isalnum())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def _dice(a: set[str], b: set[str]) -> float:
    """Compute existing Dice overlap with an empty-set zero fallback / 计算既有 Dice 重合度，空集合回退为零。"""
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _new_topic_id(turn: DialogueTurn) -> str:
    """Derive the existing topic ID from session, time and text / 按会话、时间及正文派生既有话题编号。"""
    raw = f"{turn.session_id}|{turn.at}|{turn.text}"
    return "tp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def topic_for(turn: DialogueTurn, previous: DialogueTurn | None,
               parent: DialogueTurn | None = None) -> str:
    """Choose reply-parent, prior topic or a new topic using unchanged thresholds / 以不变阈值选择回复父话题、前一话题或新话题。"""
    if (parent is not None and parent.session_id == turn.session_id
            and parent.topic_id):
        return parent.topic_id
    if previous is None or not previous.topic_id:
        return _new_topic_id(turn)
    current_at, previous_at = _parse_at(turn.at), _parse_at(previous.at)
    if current_at is not None and previous_at is not None:
        if (current_at - previous_at).total_seconds() > TOPIC_GAP_SECONDS:
            return _new_topic_id(turn)
    if _dice(_bigrams(turn.text), _bigrams(previous.text)) < TOPIC_SIMILARITY:
        return _new_topic_id(turn)
    return previous.topic_id
