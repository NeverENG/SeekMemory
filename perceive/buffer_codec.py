"""Decode legacy rows and queued Source projections without side effects.

转换旧数据行及排队的原始消息视图，不执行副作用。
"""
from __future__ import annotations

from dataclasses import replace
try:
    from ..app.contracts import DialogueTurn
except ImportError:
    from app.contracts import DialogueTurn
from .buffer_policy import _new_topic_id

def turn_from_row(row) -> DialogueTurn | None:
    """Decode supported legacy row layouts without I/O / 转换受支持的旧行布局，不执行读写。"""
    if isinstance(row, dict):
        try:
            turn = DialogueTurn(
                str(row.get("session_id") or ""),
                str(row.get("speaker_id") or ""),
                str(row.get("role") or "user"),
                str(row.get("text") or ""),
                str(row.get("at") or ""),
                str(row.get("source_id") or ""),
                str(row.get("topic_id") or ""),
                str(row.get("turn_id") or ""),
                str(row.get("reply_to") or "") or None,
            )
        except Exception:
            return None
    elif isinstance(row, (list, tuple)):
        if len(row) >= 5:
            turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]),
                                "", str(row[4]), "")
        elif len(row) == 4:
            turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]))
        elif len(row) == 3:
            turn = DialogueTurn(str(row[0]), "", str(row[1]), str(row[2]))
        else:
            return None
    else:
        return None
    if not turn.text.strip():
        return None
    if turn.topic_id:
        return turn
    return replace(turn, topic_id=_new_topic_id(turn))


def unique_by_source(items: list[DialogueTurn]) -> list[DialogueTurn]:
    """Keep one row per nonempty Source ID, retaining distinct source-less rows / 每个非空原始消息编号仅保留一行，无编号行仍分别保留。"""
    seen: set[str] = set()
    kept: list[DialogueTurn] = []
    for item in items:
        if item.source_id and item.source_id in seen:
            continue
        seen.add(item.source_id)
        kept.append(item)
    return kept
