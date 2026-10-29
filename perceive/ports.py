"""Required extraction capabilities; declarations and existing protocol exports.

声明抽取所需能力并导出现有协议，不实现模型、队列或仓储；资源归组装方管理。
"""
from __future__ import annotations

from typing import Any, Protocol

try:
    from ..app.ports import ArtifactCache, ChatModel, ExtractionStore, SourceStore
except ImportError:
    from app.ports import ArtifactCache, ChatModel, ExtractionStore, SourceStore


class TextProvider(Protocol):
    """Legacy provider text calls consumed by the compatible model adapter.

    兼容模型转接所需的旧提供方文本调用形式，具体响应由转接层处理。
    """

    async def text_chat(self, *, system_prompt: str, prompt: str, **kwargs: Any) -> Any:
        """Complete supplied text or raise; no fabricated success / 完成给定文本调用或抛错，不伪造成功。"""
        ...


__all__ = ["ArtifactCache", "ChatModel", "ExtractionStore", "SourceStore", "TextProvider"]
