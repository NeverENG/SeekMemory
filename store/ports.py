"""Required capabilities outside store; declarations only.

声明存储模块所需的外部能力，不依赖应用或宿主；连接与文件由具体存储实现管理。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

try:
    from ..core.artifact import Artifact
except ImportError:
    from core.artifact import Artifact

TraceClock = Callable[[], float]


class ArtifactReader(Protocol):
    """Read current memories for cache rebuilds; the caller owns storage.

    为缓存重建读取当前记忆，存储生命周期由调用方管理。
    """

    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]:
        """Read matching current memories; failures raise / 读取匹配的当前记忆，失败抛错。"""
        ...


__all__ = ["ArtifactReader", "TraceClock"]
