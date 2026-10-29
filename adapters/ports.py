"""Shared adapter dependencies; reuse existing application protocols.

共享适配器依赖，复用既有应用协议，不包含读写实现。
"""
try:
    from ..app.ports import ArtifactCache, SourceStore, ChatModel, ActionPort, MemoryContextRecorder, PersonaPacks
except ImportError:
    from app.ports import ArtifactCache, SourceStore, ChatModel, ActionPort, MemoryContextRecorder, PersonaPacks

__all__ = ["ArtifactCache", "SourceStore", "ChatModel", "ActionPort", "MemoryContextRecorder", "PersonaPacks"]
