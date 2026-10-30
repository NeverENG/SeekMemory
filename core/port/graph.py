"""Required external capabilities / 领域逻辑要求外部提供的能力。

Declarations only; implementations and resource lifetimes belong to callers.
仅声明依赖接口；具体实现及资源生命周期由外部管理。
"""

from __future__ import annotations

from typing import Protocol


class GraphArtifactStore(Protocol):
    """Storage needed by Graph; caller owns its lifetime / 图所需存储，生命周期由外部管理。"""

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Upsert by (src, dst, kind); errors propagate / 按两端及类型写入或更新，错误向上传递。"""
        ...

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read (other ID, kind, weight) from both ends; direction omitted / 双向查询，返回另一端、类型、权重，不含方向。"""
        ...


__all__ = ["GraphArtifactStore"]
