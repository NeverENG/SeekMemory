"""Execute AstrBot sends; runtime owns retry and audit, caller owns host context.

执行 AstrBot 发送，运行时负责重试和审计，调用方管理宿主上下文。
"""

from __future__ import annotations

from .ports import MessageHost

try:
    from ...app.runtime.contracts import ActionKind, ActionRequest, ActionResult
except ImportError:  # Top-level adapter tests / 顶层适配器测试。
    from app.runtime.contracts import ActionKind, ActionRequest, ActionResult


class AstrBotActionPort:
    """Execute host sends without owning retry, audit or terminal-state policy / 执行宿主发送，不负责重试、审计或终态规则。"""

    def __init__(self, context: MessageHost, message_factory=None) -> None:
        self.context = context
        self.message_factory = message_factory

    def _chain(self, text: str):
        """Build the host message using an injected or lazily loaded factory / 通过注入或延迟加载的工厂构造宿主消息。"""
        if self.message_factory is not None:
            return self.message_factory(text)
        from astrbot.core.message.message_event_result import MessageChain
        return MessageChain().message(text)

    async def execute(self, request: ActionRequest) -> ActionResult:
        """Return fixed send outcome codes; isolate ordinary host errors, propagate cancellation / 返回固定发送结果码，隔离普通宿主错误，传播取消。"""
        if request.kind != ActionKind.SEND_TEXT:
            return ActionResult(False, "unsupported_action")
        if not request.session_id:
            return ActionResult(False, "missing_session")
        if not str(request.text or "").strip():
            return ActionResult(False, "empty_message")
        sender = getattr(self.context, "send_message", None)
        if not callable(sender):
            return ActionResult(False, "host_unavailable")
        try:
            result = await sender(request.session_id, self._chain(request.text))
        except Exception:  # Return fixed codes, never host bodies/secrets / 返回固定码，不返回宿主正文或密钥。
            return ActionResult(False, "host_action_failed")
        return ActionResult(result is not False, "" if result is not False else "host_send_failed")

    async def send(self, session_id: str, text: str) -> bool:
        """Keep the existing boolean send compatibility entry / 保留既有布尔发送兼容入口。"""
        return (await self.execute(ActionRequest(session_id, text=text))).ok
