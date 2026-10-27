"""Host-agnostic contracts for the SeekMemory agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class Clock(Protocol):
    """Wall-clock source used by the runtime; returns UTC epoch seconds."""

    def __call__(self) -> float: ...


class AttentionLevel(str, Enum):
    AMBIENT = "ambient"
    ADDRESSED = "addressed"
    DIRECT = "direct"
    PRIVATE = "private"


class WakeAction(str, Enum):
    IGNORE = "ignore"
    OBSERVE = "observe"
    WAIT = "wait"
    REPLY = "reply"


class ActionKind(str, Enum):
    SEND_TEXT = "send_text"
    TOOL_CALL = "tool_call"
    HOST_ACTION = "host_action"


class ActionStatus(str, Enum):
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RuntimeInput:
    """One inbound event reduced to host-neutral fields.

    ``event_time`` is when the platform says the event happened. ``received_at``
    is when this process observed it. Decision time is passed explicitly to the
    runtime methods and is never inferred from either field.
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


@dataclass(frozen=True)
class RunContext:
    """One runtime unit before it becomes a durable result."""

    session_id: str
    text: str
    source_id: str = ""
    bot_id: str = ""
    event_time: float = 0.0
    received_at: float = 0.0
    run_id: str = ""


@dataclass(frozen=True)
class UserRunReceipt:
    """Identity attached to one accepted user turn."""

    decision: RunDecision
    source_id: str = ""
    turn_id: str = ""


@dataclass(frozen=True)
class RunResult:
    """Observed outcome of one runtime run."""

    run_id: str
    session_id: str
    delivered: bool
    assistant_source_id: str = ""
    response_chars: int = 0
    error: str = ""


@dataclass(frozen=True)
class ActionRecord:
    """Content-free action/handoff audit metadata.

    Message bodies, prompts, tool arguments and tool results must never be
    added here. ``action_id`` is the stable idempotency key for one action.
    """

    action_id: str
    session_id: str
    run_id: str = ""
    kind: ActionKind = ActionKind.HOST_ACTION
    status: ActionStatus = ActionStatus.ATTEMPTED
    reason: str = ""
    attempt: int = 1
    at: float = 0.0

    @property
    def terminal(self) -> bool:
        return self.status in (
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.CANCELLED,
        )


@dataclass(frozen=True)
class ProactiveDecision:
    """Pure policy result: whether this session should be considered due."""

    should_speak: bool
    reason: str
    due_at: float = 0.0


@dataclass
class SessionState:
    """Per-session timing and attention state. This is not memory."""

    session_id: str
    last_event_at: float = 0.0
    last_seen_at: float = 0.0
    last_spoke_at: float = 0.0
    quiet_until: float = 0.0
    wait_until: float = 0.0
    cooldown_until: float = 0.0
    unread_count: int = 0
    last_unread_seq: int = 0
    read_through_seq: int = 0
    ignored_streak: int = 0
    dispatch_attempts: int = 0
    next_retry_at: float = 0.0
    last_dispatched_source_id: str = ""
    last_action: str = ""
    last_reason: str = ""
    reply_cooldown_seconds: float = 30.0
    last_proactive_at: float = 0.0
    proactive_due_at: float = 0.0
    proactive_attempts: int = 0
    last_action_at: float = 0.0
    last_action_kind: str = ""
    last_action_status: str = ""


@dataclass(frozen=True)
class RunDecision:
    action: WakeAction
    reason: str
    attention: AttentionLevel = AttentionLevel.AMBIENT
    must_reply: bool = False


class SessionStateStore(Protocol):
    def get(self, session_id: str) -> SessionState: ...
    def put(self, state: SessionState) -> None: ...


class TraceSink(Protocol):
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True)
class MemoryContextRequest:
    """Host-neutral request for read-only memory context."""

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
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)


class MemoryContextPort(Protocol):
    def build_context(self, request: MemoryContextRequest) -> MemoryContext: ...


class ModelGateway(Protocol):
    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str: ...


class MessageSender(Protocol):
    async def send(self, session_id: str, text: str) -> bool: ...


class ActionSink(Protocol):
    def append(self, record: ActionRecord) -> None: ...


class ProactivePolicy(Protocol):
    def evaluate(self, state: SessionState, *, now: float) -> ProactiveDecision: ...
