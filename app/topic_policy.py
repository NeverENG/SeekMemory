"""Pure topic segmentation policy shared by live and historical ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime

from .contracts import DialogueTurn

TOPIC_GAP_SECONDS = 5400
TOPIC_SIMILARITY = 0.12


def parse_topic_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def bigrams(text: str) -> set[str]:
    clean = "".join(ch.lower() for ch in str(text or "") if ch.isalnum())
    return {clean[index:index + 2] for index in range(max(0, len(clean) - 1))}


def dice(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2.0 * len(left & right) / (len(left) + len(right))


def new_topic_id(turn: DialogueTurn) -> str:
    raw = f"{turn.session_id}|{turn.at}|{turn.text}"
    return "tp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def assign_topic(
    turn: DialogueTurn,
    previous: DialogueTurn | None,
    parent: DialogueTurn | None = None,
) -> DialogueTurn:
    """Apply reply-parent, 90-minute gap and bigram Dice boundaries."""
    if parent is not None and parent.session_id == turn.session_id and parent.topic_id:
        return replace(turn, topic_id=parent.topic_id)
    if previous is None or not previous.topic_id:
        return replace(turn, topic_id=new_topic_id(turn))
    current_at = parse_topic_time(turn.at)
    previous_at = parse_topic_time(previous.at)
    if current_at is not None and previous_at is not None:
        if (current_at - previous_at).total_seconds() > TOPIC_GAP_SECONDS:
            return replace(turn, topic_id=new_topic_id(turn))
    if dice(bigrams(turn.text), bigrams(previous.text)) < TOPIC_SIMILARITY:
        return replace(turn, topic_id=new_topic_id(turn))
    return replace(turn, topic_id=previous.topic_id)
