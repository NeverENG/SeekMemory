"""Build a bounded, read-only model input from exact unread Source evidence.

从精确的未读 Source 证据构造有界、只读的模型输入。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

try:
    from ...core.domain.memory.source import Source
except ImportError:
    from core.domain.memory.source import Source

from .contracts import SessionState

MAX_UNREAD_MESSAGES = 32
MAX_UNREAD_BYTES = 16_384


class UnreadSourceReader(Protocol):
    """Read immutable Sources by exact identity / 按确切编号读取不可变 Source。"""

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]: ...


@dataclass(frozen=True)
class PreparedUnreadInput:
    text: str
    latest_source_id: str
    read_through_seq: int


class UnreadContextUnavailable(Exception):
    """Missing, ambiguous, or over-budget unread evidence / 未读证据缺失、有歧义或超预算。"""


def assemble_unread_input(state: SessionState, reader: UnreadSourceReader) -> PreparedUnreadInput:
    """Return the next bounded prefix; never acknowledge messages outside it.

    返回下一段有界的未读前缀；绝不确认本批之外的消息。
    """
    count = state.last_unread_seq - state.read_through_seq
    mapping = state.unread_sources
    if count <= 0 or len(mapping) > count or len(set(mapping.values())) != len(mapping):
        raise UnreadContextUnavailable()
    # Verify the whole index, but require Source evidence only for this bounded prefix.
    # 核验全部索引，但只要求本批有界前缀的 Source 证据齐全。
    if any(not isinstance(seq, str) or not seq.isdecimal()
           or str(int(seq)) != seq
           or not (state.read_through_seq < int(seq) <= state.last_unread_seq)
           for seq in mapping):
        raise UnreadContextUnavailable()
    ids = [mapping.get(str(seq), "") for seq in range(
        state.read_through_seq + 1,
        min(state.last_unread_seq, state.read_through_seq + MAX_UNREAD_MESSAGES) + 1,
    )]
    if not all(ids):
        raise UnreadContextUnavailable()
    sources = reader.sources_by_ids(ids)
    if any((source := sources.get(source_id)) is None or source.id != source_id
           or source.session_id != state.session_id or source.role != "user"
           or not str(source.text or "").strip() for source_id in ids):
        raise UnreadContextUnavailable()

    def render(batch: list[str]) -> str:
        if len(batch) == 1:
            return sources[batch[0]].text
        speakers: dict[str, int] = {}
        lines = []
        for index, source_id in enumerate(batch, 1):
            source = sources[source_id]
            speaker_number = speakers.setdefault(source.speaker_id, len(speakers) + 1)
            lines.append(
                f"{index}. 发言者{speaker_number}: {json.dumps(source.text, ensure_ascii=False)}"
            )
        return "同一会话中尚未回复的用户消息（按接纳顺序）：\n" + "\n".join(lines)

    selected: list[str] = []
    text = ""
    for source_id in ids:
        candidate = render([*selected, source_id])
        if len(candidate.encode("utf-8")) > MAX_UNREAD_BYTES:
            if not selected:
                raise UnreadContextUnavailable()
            break
        selected.append(source_id)
        text = candidate
    return PreparedUnreadInput(text, selected[-1], state.read_through_seq + len(selected))
