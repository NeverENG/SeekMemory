"""Bounded read-only ancestry over existing tree edges / 基于现有树连接的有界只读祖先查询。"""

from __future__ import annotations

from ...port.tree import TreeEdgeReader

EDGE_PREFIX = "tree_child:"
DEFAULT_MAX_DEPTH = 32


def tree_child_kind(parent_id: str) -> str:
    """Encode the existing parent-scoped edge kind / 使用既有父节点作用域编码连接类型。"""
    return EDGE_PREFIX + parent_id


def parent_id(node_id: str, edges: TreeEdgeReader) -> str | None:
    """Find one unambiguous parent; ignore child links and unrelated edges / 查找唯一父节点，忽略子节点和无关连接。"""
    if not node_id:
        return None
    found: str | None = None
    for edge in edges.edges_of(node_id):
        if len(edge) < 2:
            continue
        other, kind = edge[0], edge[1]
        if not other or other == node_id or kind != tree_child_kind(other):
            continue
        if found is not None and found != other:
            return None
        found = other
    return found


def ancestor_ids(node_id: str, edges: TreeEdgeReader, *,
                 max_depth: int = DEFAULT_MAX_DEPTH) -> tuple[str, ...]:
    """Walk upward at most max_depth steps; stop at cycles or ambiguity.

    最多向上读取 max_depth 层；遇到环或多父节点即停止，不修改存储。
    """
    if type(max_depth) is not int or max_depth < 1:
        raise ValueError("max_depth must be a positive integer")
    result: list[str] = []
    seen = {node_id}
    current = node_id
    for _ in range(max_depth):
        parent = parent_id(current, edges)
        if parent is None or parent in seen:
            break
        result.append(parent)
        seen.add(parent)
        current = parent
    return tuple(result)
