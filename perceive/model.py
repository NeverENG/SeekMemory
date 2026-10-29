"""Adapt the existing host provider to ChatModel at its compatible import path.

在兼容导入路径将既有宿主提供方转换为 ChatModel，不拥有提供方生命周期。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .ports import TextProvider

try:
    from ..app.contracts import ChatRequest, ChatResponse
except ImportError:
    from app.contracts import ChatRequest, ChatResponse


class ProviderChatModel:
    """Perform bounded provider calls with neutral response metadata / 限时调用提供方并返回通用响应元数据。"""

    def __init__(self, provider: TextProvider, timeout: float = 60.0) -> None:
        self.provider = provider
        self.timeout = float(timeout)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Call the provider; preserve timeout/cancellation and legacy response defaults.

        调用提供方，保留超时、取消及旧响应默认行为。
        """
        started = time.monotonic()
        kwargs = {}
        if request.model:
            kwargs["model"] = request.model
        resp = await asyncio.wait_for(
            self.provider.text_chat(
                system_prompt=request.system_prompt, prompt=request.prompt, **kwargs
            ),
            timeout=self.timeout,
        )
        usage = getattr(resp, "usage", None)
        meta = self.provider.meta() if hasattr(self.provider, "meta") else None
        return ChatResponse(
            text=str(getattr(resp, "completion_text", "") or ""),
            model=str(getattr(meta, "model", "") or ""),
            provider_id=str(getattr(meta, "id", "") or ""),
            usage_in=int(getattr(usage, "input", 0) or 0),
            usage_cached=int(getattr(usage, "input_cached", 0) or 0),
            usage_out=int(getattr(usage, "output", 0) or 0),
            response_id=str(getattr(resp, "id", "") or ""),
            latency_ms=int((time.monotonic() - started) * 1000),
        )
