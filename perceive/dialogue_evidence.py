"""Render dialogue and read immutable parent evidence without re-queuing it.

转换对话并读取不可变父消息证据，不重新排队；读取接口由调用方提供。
"""
from __future__ import annotations

import json

try:
    from ..app.contracts import DialogueTurn
    from ..app.ports import SourceStore
except ImportError:
    from app.contracts import DialogueTurn
    from app.ports import SourceStore


def _quote_prompt_value(value: str) -> str:
    """Keep a model-facing field on one line without changing the Source / 仅编码模型输入，不修改 Source。"""
    return (json.dumps(value, ensure_ascii=False)
            .replace("\u0085", "\\u0085")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def _header_field(value: str) -> str:
    """Escape line breaks and quotes without changing ordinary metadata / 转义控制字符，普通元数据保持原样。"""
    return _quote_prompt_value(str(value))[1:-1]


def _dialog_rows(items: list[DialogueTurn]) -> list[DialogueTurn]:
    """Keep every supplied row; the caller already owns chunk limits / 保留所有给定行，分块限额已由调用方负责。"""
    return list(items)


def dialogue_of(
    items: list[DialogueTurn], *, include_topic: bool = False
) -> str:
    """Render supplied dialogue with Source IDs and optional topic labels / 以原始消息编号及可选话题标记转换给定对话。"""
    lines = []
    for turn in _dialog_rows(items):
        role = _header_field(turn.role)
        who = f"{role}({_header_field(turn.speaker_id)})" if turn.speaker_id else role
        if turn.source_id:
            who = f"{who}[{_header_field(turn.source_id)}]"
        if turn.role == "assistant" and turn.reply_to:
            who += f" reply_to={_header_field(turn.reply_to)}"
        prefix = f"[{_header_field(turn.at)}] " if turn.at else ""
        topic = f"topic={_header_field(turn.topic_id)} " if include_topic and turn.topic_id else ""
        # Only the model-facing projection is escaped; immutable Source text stays original.
        # 仅转义模型输入视图，不修改不可变 Source 正文。
        lines.append(f"{prefix}{topic}{who}: {_quote_prompt_value(turn.text)}")
    return "\n".join(lines)


def recover_parents(items: list[DialogueTurn], sources: SourceStore | None) -> list[DialogueTurn]:
    """Read same-session user parents for reply evidence; never re-queue or rewrite them / 读取同会话用户父消息作为回复证据，不重新排队或写入。"""
    rows = list(items)
    if sources is None:
        return rows
    present = {turn.source_id for turn in items if turn.source_id}
    wanted: list[str] = []
    for turn in items:
        parent_id = str(turn.reply_to or "")
        if turn.role != "assistant" or not parent_id or parent_id in present:
            continue
        if parent_id not in wanted:
            wanted.append(parent_id)
    if not wanted:
        return rows
    source_rows = sources.sources_by_ids(wanted)
    out: list[DialogueTurn] = []
    added: set[str] = set()
    for turn in items:
        parent_id = str(turn.reply_to or "") if turn.role == "assistant" else ""
        parent = source_rows.get(parent_id) if parent_id else None
        # Only the exact same-session user parent may enter pairing context.
        # 只有同会话且被实际回复的用户父消息才可进入配对上下文。
        if parent is not None and parent.id not in present and parent.id not in added:
            same_session = parent.session_id == turn.session_id
            if parent.role == "user" and same_session and parent.id == parent_id:
                added.add(parent.id)
                out.append(
                    DialogueTurn(
                        parent.session_id,
                        parent.speaker_id,
                        parent.role,
                        parent.text,
                        parent.at,
                        parent.id,
                        "",
                        parent.turn_id,
                        parent.reply_to,
                    )
                )
        out.append(turn)
    return out
