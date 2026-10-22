"""现有离线数据集共用的图检索/BM25对照，不修改金标或隐私规则。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from core.artifact import Artifact, content_of
from core.graph import Graph
from recall.assemble import build
from recall.gate import pinned
from recall.retriever import GraphRetriever, HybridRetriever
from recall.score import select
from store.cache import Cache


@dataclass(frozen=True)
class Query:
    text: str
    expected: tuple[str, ...]


def comparison(cache: Cache, graph: Graph, pool: list[Artifact],
               queries: list[Query]) -> list[str]:
    """以相同 top-k/预算/探索配置输出两条真实检索路径的度量。"""
    rows = ["", "## BM25 开关对照", "",
            "| 配置 | 命中 | 检索候选噪声 | 平均注入字数 | 平均耗时（含首次建索引） |",
            "|---|---:|---:|---:|---:|"]
    for label, retriever in (("关闭", GraphRetriever(graph, cache)),
                             ("开启 C=8/weight=1", HybridRetriever(graph, cache))):
        hits = total = chars = noise = selected = 0
        elapsed = 0.0
        for query in queries:
            start = time.perf_counter()
            picked = select(retriever.retrieve(query.text, pool), query.text, 0.0,
                            k=8, explore=0.0, lexical_weight=1.0)
            block = build(pinned(cache) + picked, budget=600)
            elapsed += time.perf_counter() - start
            chars += len(block)
            if query.expected:
                total += 1
                hits += any(term.lower() in block.lower() for term in query.expected)
                selected += len(picked)
                noise += sum(not any(term.lower() in content_of(art).lower()
                                     for term in query.expected) for art in picked)
        count = max(1, len(queries))
        rows.append(f"| {label} | {hits}/{total} | {noise / max(1, selected):.2%} | "
                    f"{chars / count:.2f} | {elapsed * 1000 / count:.3f} ms |")
    rows += ["", "> 噪声按可答题选中候选是否含金标词统计；与消融基准的字数加权噪声口径不同。",
             "> 本节仅比较检索/组装组件；完整 scope/disclosure 路径由 pipeline 集成测试验证。"]
    return rows
