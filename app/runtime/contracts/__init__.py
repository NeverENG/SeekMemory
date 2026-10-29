"""Compatibility exports for host-neutral runtime declarations; no implementation / 与宿主无关的运行时声明兼容导出，不包含实现。"""

from .actions import (
    ActionKind,
    ActionPort,
    ActionRecord,
    ActionRequest,
    ActionResult,
    ActionSink,
    ActionStatus,
)
from .events import (
    AttentionDecision,
    AttentionLevel,
    RunContext,
    RunDecision,
    RunResult,
    RuntimeInput,
    UserRunReceipt,
    WakeAction,
)
from .ports import (
    Clock,
    MemoryContext,
    MemoryContextRecorder,
    MemoryContextPort,
    MemoryContextRequest,
    MessageSender,
    ModelGateway,
    TraceSink,
)
from .proactive import ProactiveDecision, ProactivePolicy
from .sessions import SessionState, SessionStateStore

__all__ = [
    "ActionKind",
    "ActionPort",
    "ActionRecord",
    "ActionRequest",
    "ActionResult",
    "ActionSink",
    "ActionStatus",
    "AttentionDecision",
    "AttentionLevel",
    "Clock",
    "MemoryContext",
    "MemoryContextPort",
    "MemoryContextRecorder",
    "MemoryContextRequest",
    "MessageSender",
    "ModelGateway",
    "ProactiveDecision",
    "ProactivePolicy",
    "RunContext",
    "RunDecision",
    "RunResult",
    "RuntimeInput",
    "SessionState",
    "SessionStateStore",
    "TraceSink",
    "UserRunReceipt",
    "WakeAction",
]
