"""Transient, already-extracted host facts; never a persisted event / 临时宿主事实，并非持久事件。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HostRequest:
    """Trusted host facts for one inbound message; field defaults match RuntimeInput.

    已由宿主提取的一条入站消息事实；默认值与 RuntimeInput 保持一致。
    """

    session_id: str
    text: str
    event_time: float = 0.0
    received_at: float = 0.0
    speaker_id: str = ""
    private: bool = False
    mentioned: bool = False
    question: bool = False
    unread_count: int = 0
    unread_seq: int = 0
    scene: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    self_id: str = ""
    role: str = ""
    addressed: bool = False
    reply_to_me: bool = False
    event_id: str = ""
    kind: str = "message"
