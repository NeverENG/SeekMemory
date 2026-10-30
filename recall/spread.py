"""Read graph/cache neighbors and compute bounded activation without changing the graph.

读取图及缓存邻居，计算有上限的激活，不改变图。
"""

from __future__ import annotations

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactCache
    from ..core.domain.memory.graph import Graph
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactCache
    from core.domain.memory.graph import Graph

DECAY = 0.5
MAX_PER_ROUND = 20
MAX_ACTIVATION = 1.0


def _neighbours(graph: Graph, node_id: str) -> list[tuple[str, float]]:
    """Read graph neighbors; unavailable edges yield no expansion / 读取图邻居，连接不可用时不扩展。"""
    try:
        return list(graph.neighbours(node_id))
    except Exception:
        return []


def _alive(cache: ArtifactCache, node_id: str) -> bool:
    """Reject explicitly inactive cached memory; preserve the existing miss fallback / 拒绝明确非有效的缓存记忆，保留既有未命中回退。"""
    try:
        art = cache.get(node_id)
    except Exception:
        return True
    if art is None:
        return True
    return getattr(getattr(art, "header", None), "state", "active") == "active"


def _weight(value: float) -> float:
    """Read and bound the existing weight with a zero invalid-value fallback / 读取并限定既有权重，无效值回退为零。"""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def activate(
    seed_ids: list[str],
    graph: Graph,
    cache: ArtifactCache,
    rounds: int = 2,
) -> dict[str, float]:
    """Compute bounded max-path activation from supplied seeds without graph mutation / 从给定种子计算有上限的最大路径激活，不修改图。"""
    scores: dict[str, float] = {sid: MAX_ACTIVATION for sid in seed_ids if sid}
    frontier = dict(scores)
    for _ in range(max(0, rounds)):
        candidates: dict[str, float] = {}
        for node_id, value in frontier.items():
            for nid, weight in _neighbours(graph, node_id):
                if not nid or not _alive(cache, nid):
                    continue
                contribution = value * DECAY * _weight(weight)
                best = max(scores.get(nid, 0.0), candidates.get(nid, 0.0))
                if contribution <= best:
                    continue
                candidates[nid] = min(MAX_ACTIVATION, contribution)
        if not candidates:
            break
        ranked = sorted(candidates.items(), key=lambda item: (-item[1], item[0]))
        frontier = dict(ranked[:MAX_PER_ROUND])
        for nid, value in frontier.items():
            scores[nid] = max(scores.get(nid, 0.0), value)
    return scores
