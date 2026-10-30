"""Read-only tree edge capability / 树查询所需的只读连接能力。"""

from __future__ import annotations

from typing import Protocol


class TreeEdgeReader(Protocol):
    """Supply stored edges without exposing SQL or cache / 提供已存连接，不暴露 SQL 或缓存。"""

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Return adjacent (other ID, kind, weight) rows / 返回邻接的（另一端编号、类型、权重）。"""
        ...
