"""Resolve the host provider and adapt runtime text generation; caller owns context.

解析宿主提供方并转接运行时文本生成，上下文由调用方管理。
"""

from __future__ import annotations

from .ports import ProviderHost


class AstrBotModelGateway:
    """Resolve the session provider and adapt existing text generation / 解析会话提供方并转接既有文本生成。"""

    def __init__(self, context: ProviderHost) -> None:
        self.context = context

    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str:
        """Call the existing host provider and return text; failures/cancellation propagate / 调用既有宿主提供方并返回文本，失败及取消向上传递。"""
        provider = await self.context.get_using_provider_async(session_id)
        if provider is None:
            raise RuntimeError("no_provider")
        response = await provider.text_chat(
            prompt=str(prompt or ""),
            system_prompt=system_prompt or None,
        )
        return str(getattr(response, "completion_text", "") or "").strip()
