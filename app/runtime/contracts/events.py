"""Host-neutral event and decision data; no state mutation or I/O / 与宿主无关的事件及决策数据，不修改状态或读写。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
class AttentionLevel(str, Enum):
    """Attention categories, independent of a host / 与宿主无关的注意力类别。"""
    AMBIENT = "ambient"
    ADDRESSED = "addressed"
    DIRECT = "direct"
    PRIVATE = "private"


class WakeAction(str, Enum):
    """Supported observation, waiting and reply decisions / 支持的观察、等待及回复决策。"""
    IGNORE = "ignore"
    OBSERVE = "observe"
    WAIT = "wait"
    REPLY = "reply"


@dataclass(frozen=True)
class RuntimeInput:
    """Reduced inbound event; event_time is platform time, received_at is observation time, and decision time is explicit.

    精简入站事件，event_time 为平台时间，received_at 为接收时间，决策时间单独传入。
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
    # Optional host-neutral context preserves existing callers.
    # 可选的平台无关上下文保留旧调用方式。
    # scene: private/group/channel/thread/comment; thread_id carries nesting.
    # scene 为上述场景值，thread_id 表达嵌套评论或话题。
    # role: owner/admin/member/bot/system; kind currently handles message only.
    # role 为上述角色值，kind 当前只处理 message，其他事件类别预留。
    scene: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    self_id: str = ""
    role: str = ""
    addressed: bool = False
    reply_to_me: bool = False
    event_id: str = ""
    kind: str = "message"

    @property
    def is_owner(self) -> bool:
        """Derive owner status without adding a serialized field / 派生主人状态，不增加序列化字段。"""
        return self.role == "owner"


@dataclass(frozen=True)
class RunContext:
    """Caller-supplied input for one runtime execution / 调用方提供的一次运行输入。"""

    session_id: str
    text: str
    source_id: str = ""
    bot_id: str = ""
    event_time: float = 0.0
    received_at: float = 0.0
    run_id: str = ""


@dataclass(frozen=True)
class UserRunReceipt:
    """Accepted message identity and bounded acknowledgement cursor / 已接收消息标识及有界确认位置。"""

    decision: RunDecision
    source_id: str = ""
    turn_id: str = ""
    read_through_seq: int | None = None


@dataclass(frozen=True)
class RunResult:
    """Observed delivery and write-back result; writeback_pending may accompany delivered=True.

    观察到的交付及写回结果，delivered=True 时仍可能有 writeback_pending。
    """

    run_id: str
    session_id: str
    delivered: bool
    assistant_source_id: str = ""
    response_chars: int = 0
    error: str = ""

@dataclass(frozen=True)
class RunDecision:
    """Selected action, reason and attention requirement / 选定动作、原因及注意力要求。"""
    action: WakeAction
    reason: str
    attention: AttentionLevel = AttentionLevel.AMBIENT
    must_reply: bool = False


@dataclass(frozen=True)
class AttentionDecision:
    """Pure decision and per-speaker follow-up update / 纯决策及按说话人区分的后续回复变化。"""

    action: WakeAction
    reason: str
    attention: AttentionLevel = AttentionLevel.AMBIENT
    must_reply: bool = False
    followup_speaker_id: str = ""
    followup_remaining: int | None = None

    def runtime_decision(self) -> RunDecision:
        """Project the action without applying follow-up changes / 投影动作决策，不执行后续回复状态变化。"""
        return RunDecision(
            action=self.action,
            reason=self.reason,
            attention=self.attention,
            must_reply=self.must_reply,
        )

