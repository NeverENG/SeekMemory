"""Transient action inputs, content-free audit data and external capability declarations / 临时动作输入、不含正文的审计数据及外部能力声明。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ActionKind(str, Enum):
    """Supported host action vocabulary / 支持的宿主动作词表。"""
    SEND_TEXT = "send_text"
    TOOL_CALL = "tool_call"
    HOST_ACTION = "host_action"


class ActionStatus(str, Enum):
    """Attempted and terminal action states / 动作尝试与终态词表。"""
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ActionRequest:
    """Transient execution input; its text must not enter action audit / 临时执行输入，正文不得进入动作审计。"""

    session_id: str
    kind: ActionKind = ActionKind.SEND_TEXT
    text: str = ""


@dataclass(frozen=True)
class ActionResult:
    """Observed host result without audit transition policy / 宿主执行结果，不负责审计终态策略。"""

    ok: bool
    reason: str = ""
@dataclass(frozen=True)
class ActionRecord:
    """Content-free audit; action_id is stable, and bodies/prompts/tool payloads are excluded.

    不含正文的审计，action_id 稳定，不保存消息、提示词或工具内容。
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
        """Whether status is success, failure or cancellation / 是否为成功、失败或取消终态。"""
        return self.status in (
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.CANCELLED,
        )
class ActionPort(Protocol):
    """Host execution capability supplied by composition / 组装方提供的宿主执行能力。"""
    async def execute(self, request: ActionRequest) -> ActionResult:
        """Execute a transient request and report the observed outcome / 执行临时请求，返回观察到的结果。"""
        ...


class ActionSink(Protocol):
    """Persistence capability for content-free action audit / 不含正文的动作审计存储能力。"""
    def append(self, record: ActionRecord) -> None:
        """Persist an action record; failures raise / 保存动作记录，失败抛异常。"""
        ...
