"""Add bounded same-scope graph edges as best-effort enrichment; legacy persist commits before cache.

尽力补充有数量上限的同范围图连接，旧 persist 入口在缓存前提交。
"""

from __future__ import annotations

import re
from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, content_of, revise
    from ..core.graph import Graph
    from .ports import ArtifactCache, ArtifactStore
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, content_of, revise
    from core.graph import Graph
    from maintain.ports import ArtifactCache, ArtifactStore

SIMILAR_BAR = 0.45
MAX_SIMILAR = 3
MAX_TEMPORAL = 2
TEMPORAL_WEIGHT = 0.3
MAX_EDGES = 5

_PUNCT = re.compile(r"[^\w\u4e00-\u9fff]+")


def _text(art: Artifact) -> str:
    """Read memory text with existing malformed-row fallback / 按既有坏行回退读取记忆正文。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - Isolate malformed memories / 隔离格式错误的记忆。
        text = ""
    return str(text or art.payload.get("text") or "")


def _bigrams(text: str) -> set[str]:
    """Compute existing punctuation-normalized pairs, preserving short input behavior / 计算既有去标点二元组，保留短输入行为。"""
    plain = _PUNCT.sub("", str(text or "")).lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[index : index + 2] for index in range(len(plain) - 1)}


def _overlap(left: str, right: str) -> float:
    """Compute the existing module-specific pair overlap / 计算既有模块各自的二元组重合度。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _day(value: Any) -> str:
    """Parse the existing date prefix or return None / 解析既有日期前缀，无效时返回空。"""
    text = str(value or "")
    return text[:10] if len(text) >= 10 else ""


def _edges(artifacts: ArtifactStore, node_id: str) -> list[tuple[str, str, float]]:
    """Read graph edges; unavailable reads yield an empty optional enhancement view / 读取图连接，读取不可用时可选增强视图为空。"""
    try:
        return list(artifacts.edges_of(node_id))
    except Exception:  # noqa: BLE001
        return []


def _has_edge(artifacts: ArtifactStore, src: str, dst: str, kind: str | None = None) -> bool:
    """Read whether an existing connection matches the requested kind / 读取已有连接是否匹配请求类型。"""
    for edge in _edges(artifacts, src):
        if len(edge) < 3 or edge[0] != dst:
            continue
        if kind is None or edge[1] == kind:
            return True
    return False


def _candidate_pool(art: Artifact, cache: ArtifactCache) -> list[Artifact]:
    """Read other active ordinary memories with the same scope / 读取相同范围内其他有效普通记忆。"""
    scope = str(art.header.scope or "private")
    return [
        other
        for other in cache.active("memory")
        if other.header.id != art.header.id
        and other.header.state == "active"
        and str(other.header.scope or "private") == scope
    ]


def _link(art: Artifact, graph: Graph, cache: ArtifactCache,
          created: str | None = None) -> int:
    """Create existing bounded similar/temporal edges without changing memory revisions / 创建既有有限相似及时间连接，不改变记忆版本。"""
    artifacts = getattr(graph, "artifacts", None)
    if artifacts is None:
        return 0
    pool = _candidate_pool(art, cache)
    room = MAX_EDGES - len(_edges(artifacts, art.header.id))
    if room <= 0 or not pool:
        return 0

    text = _text(art)
    similar = [
        (_overlap(text, _text(other)), other)
        for other in pool
    ]
    similar = sorted(
        ((score, other) for score, other in similar if score > SIMILAR_BAR),
        key=lambda item: (-item[0], item[1].header.id),
    )

    added = 0
    for score, other in similar[:MAX_SIMILAR]:
        if added >= room:
            break
        other_id = other.header.id
        if len(_edges(artifacts, other_id)) >= MAX_EDGES:
            continue
        if _has_edge(artifacts, art.header.id, other_id):
            continue
        try:
            graph.link(art.header.id, other_id, "similar", score)
        except Exception:  # noqa: BLE001 - Isolate one failed edge / 隔离一条失败连接。
            continue
        added += 1

    day = _day(created or art.header.time.created)
    if not day or added >= room:
        return added
    same_day = [
        other
        for other in pool
        if _day(other.header.time.created) == day
        and not _has_edge(artifacts, art.header.id, other.header.id)
    ]
    same_day.sort(key=lambda other: (other.header.time.created, other.header.id),
                  reverse=True)
    temporal = 0
    for other in same_day:
        if added >= room or temporal >= MAX_TEMPORAL:
            break
        other_id = other.header.id
        if len(_edges(artifacts, other_id)) >= MAX_EDGES:
            continue
        try:
            graph.link(art.header.id, other_id, "temporal", TEMPORAL_WEIGHT)
        except Exception:  # noqa: BLE001
            continue
        added += 1
        temporal += 1
    return added


def link_new(art: Artifact, graph: Graph | None, cache: ArtifactCache | None,
             created: str | None = None) -> int:
    """Attempt optional graph linking; failure never negates committed memory / 尝试可选图建联，失败不否定已提交记忆。"""
    if graph is None or cache is None:
        return 0
    try:
        return _link(art, graph, cache, created)
    except Exception:  # noqa: BLE001 - Optional linking never negates persistence / 可选建联不能否定持久化。
        return 0


def persist(art: Artifact, artifacts: ArtifactStore,
            cache: ArtifactCache | None, graph: Graph | None) -> int:
    # Compatibility writer uses CAS / 兼容写入使用预期版本提交。
    """Keep legacy CAS persistence, followed by cache and optional graph linking / 保留旧预期版本持久化，随后更新缓存及可选图建联。"""
    existing = artifacts.get(art.header.id)
    if existing is None:
        op = "create"
        expected = 0
    else:
        op = "revise"
        expected = existing.header.revision
        if art.header.revision <= existing.header.revision:
            art = revise(
                existing,
                payload=art.payload,
                state=art.header.state,
                scope=art.header.scope,
                strength=art.header.strength,
                lineage=art.header.lineage,
                said_by=art.header.said_by,
                shareable=art.header.shareable,
                subject_id=art.header.subject_id,
            )
    artifacts.commit(art, expected_revision=expected, op=op, reason="persist",
              source_ids=tuple(art.header.lineage.sources))
    if cache is not None:
        cache.put(art)
    return link_new(art, graph, cache)
