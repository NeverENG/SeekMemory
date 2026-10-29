"""Compute existing literal clusters and impression revision groups without I/O.

计算既有字面聚类及印象版本组，不执行读写。
"""

from __future__ import annotations

import datetime
import re
from collections import Counter

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from .ports import ArtifactCache, ArtifactStore
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from maintain.ports import ArtifactCache, ArtifactStore

from .plans import RevisionPlan, RevisionWrite

DEFAULT_MERGE_THRESHOLD = 0.6


def _clean(text: str) -> str:
    """Normalize existing whitespace for literal clustering / 规范化既有空白以进行字面聚类。"""
    return re.sub(r"\s+", " ", text or "").strip()


try:
    from ..app.text_rules import word_bigrams as _bigrams, word_jaccard as _similarity
except ImportError:
    from app.text_rules import word_bigrams as _bigrams, word_jaccard as _similarity


def _text_of(art: Artifact) -> str:
    """Read memory text with existing malformed-row fallback / 按既有坏行回退读取记忆正文。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - Isolate one malformed node / 隔离单个格式错误节点。
        text = ""
    return _clean(text or str(art.payload.get("text") or ""))


def _summarize_texts(texts: list[str]) -> str:
    """Prepare existing deterministic impression wording from clustered texts / 根据聚类文本准备既有确定性印象措辞。"""
    parts: list[str] = []
    for raw in texts:
        text = _clean(raw).split("。")[0].strip("，,；;、 ")
        text = re.sub(r"^(他|她|你)(经常|总是|老是|一直|常常|平时|最近)?", "", text)
        text = re.sub(
            r"^(今天|昨天|前天|那天|刚才|最近|上周|周末|晚上|早上|中午|下午)",
            "",
            text,
        )
        text = re.sub(r"^(又|总是|老是)", "", text)
        text = text.strip("，,；;、 ")
        text = re.sub(r"[啊呀吧呢哦嘛]+$", "", text)
        if len(text) > 32:
            text = text[:32] + "…"
        if text and text not in parts:
            parts.append(text)
    if not parts:
        return "他经常有些说不上来的习惯，具体是什么，还得再想想。"
    if len(parts) == 1:
        return f"他经常{parts[0]}。"
    if len(parts) == 2:
        return f"他经常{parts[0]}，也常{parts[1]}。"
    return f"他经常{parts[0]}，也常{parts[1]}，偶尔{parts[2]}。"


def _cluster_indices(texts: list[str], threshold: float) -> list[list[int]]:
    """Cluster above the existing similarity threshold; keep groups of at least three / 按既有相似阈值聚类，保留至少三项的组。"""
    parent = list(range(len(texts)))

    def find(index: int) -> int:
        """Resolve and compress the existing cluster-parent path.

        解析并压缩既有聚类父节点路径。
        """
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _similarity(texts[i], texts[j]) > threshold:
                root_i, root_j = find(i), find(j)
                if root_i != root_j:
                    parent[root_j] = root_i

    groups: dict[int, list[int]] = {}
    for index in range(len(texts)):
        groups.setdefault(find(index), []).append(index)
    return [indices for indices in groups.values() if len(indices) >= 3]


def _majority(arts: list[Artifact], key: str, default: str) -> str:
    """Read the most frequent supplied payload value or default / 读取给定内容值的众数，缺失时使用默认值。"""
    values = [
        str(art.payload.get(key))
        for art in arts
        if isinstance(art.payload.get(key), str) and art.payload.get(key)
    ]
    return Counter(values).most_common(1)[0][0] if values else default


def cluster_plan(members: list[Artifact], texts: list[str], now: str) -> RevisionPlan:
    """Prepare one create/retire group using existing cluster wording / 按既有聚类措辞准备一个新建及停用版本组。"""
    strengths = [art.header.strength for art in members]
    count = len(members)
    payload = {
        "text": _summarize_texts([texts[index] for index in range(len(texts))]),
        "level": "impression",
        "shape": "pattern",
        "chrono": "once",
        "about": _majority(members, "about", "other"),
        "first": False,
    }
    owner_umo = _majority(members, "owner_umo", "")
    if owner_umo:
        payload["owner_umo"] = owner_umo
    sources = tuple(
        dict.fromkeys(
            source for art in members for source in art.header.lineage.sources
        )
    )
    art = make(
        "memory",
        payload,
        scope=members[0].header.scope,
        strength=Strength(
            weight=max(item.weight for item in strengths) * 1.2,
            confidence=max(item.confidence for item in strengths),
            arousal=sum(item.arousal for item in strengths) / count,
            valence=sum(item.valence for item in strengths) / count,
            funny=sum(item.funny for item in strengths) / count,
        ),
        lineage=Lineage(
            sources=sources,
            derived_from=tuple(member.header.id for member in members),
        ),
        time=TimeSpan(created=now, updated=now),
        said_by="inferred",
        subject_id=str(members[0].header.subject_id or ""),
    )
    writes = [(art, 0, sources)]
    for member in members:
        writes.append((
            revise(member, state="merged"),
            member.header.revision,
            tuple(member.header.lineage.sources),
        ))
    return RevisionPlan(tuple(RevisionWrite(art, revision, sources) for art, revision, sources in writes),
                        "merge", f"merge {count} memories into impression")
