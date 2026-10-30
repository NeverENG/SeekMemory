"""Runtime memory-context data contracts / 运行时记忆上下文数据契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class MemoryContextRequest:
    """Host-neutral input for read-only memory retrieval / 与宿主无关的只读记忆检索输入。"""

    session_id: str
    query: str = ""
    source_id: str = ""
    speaker_id: str = ""
    private: bool = False
    event_time: float = 0.0
    received_at: float = 0.0
    now: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class MemoryContext:
    """Disclosed context text and diagnostic metadata / 已披露的上下文文本及诊断信息。"""
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)
