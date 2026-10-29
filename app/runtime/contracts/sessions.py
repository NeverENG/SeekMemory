"""Session scheduling data and its storage declaration; distinct from memory truth / 会话调度数据及存储声明，与记忆事实区分。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
@dataclass
class SessionState:
    """Mutable per-session scheduling state, separate from Source and memory / 按会话保存的可变调度状态，与原始消息及记忆分开。"""

    session_id: str
    revision: int = 0
    last_event_at: float = 0.0
    last_seen_at: float = 0.0
    last_spoke_at: float = 0.0
    quiet_until: float = 0.0
    wait_until: float = 0.0
    unread_count: int = 0
    last_unread_seq: int = 0
    read_through_seq: int = 0
    ignored_streak: int = 0
    dispatch_attempts: int = 0
    next_retry_at: float = 0.0
    last_dispatched_source_id: str = ""
    last_action: str = ""
    last_reason: str = ""
    last_proactive_at: float = 0.0
    proactive_due_at: float = 0.0
    proactive_attempts: int = 0
    followup_by_speaker: dict[str, int] = field(default_factory=dict)


class SessionStateStore(Protocol):
    """Session persistence supplied by composition; operations may raise / 组装方提供的会话存储，操作可能抛异常。"""
    def get(self, session_id: str) -> SessionState:
        """Read session state, defaulting only when genuinely absent / 读取会话状态，仅确实不存在时使用默认值。"""
        ...
    def put(self, state: SessionState) -> None:
        """Persist state before success; failures must be observable / 保存成功后再返回，失败必须可被识别。"""
        ...
