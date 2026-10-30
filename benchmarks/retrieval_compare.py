"""Report component retrieval comparisons; privacy is evaluated by the full pipeline.

报告组件检索对照，隐私由完整管线验证。
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import SimpleNamespace

from .memory_execution import component_rows
from .memory_metrics import summarize


@dataclass(frozen=True)
class Query:
    """Describe unchanged expected text fragments / 描述不变的期望文本片段。"""

    text: str
    expected: tuple[str, ...]


def comparison(cache, graph, pool, queries: list[Query]) -> list[str]:
    """Keep the shared report entry while counting negative-query noise / 保留共用报告入口，同时统计无答案题噪声。"""
    names = ("core.domain.memory.artifact", "recall.retriever", "recall.score", "recall.gate", "recall.assemble")
    modules = SimpleNamespace(**{name.rsplit(".", 1)[-1]: importlib.import_module(name) for name in names})
    cases = [SimpleNamespace(text=q.text, expect=q.expected, expect_level=None) for q in queries]
    lines = ["", "## BM25 component comparison / BM25 组件对照", "",
             "| 配置 | 可答题最终命中 | 无答案误召回（候选/上下文） | 候选噪声（含无答案题） | 平均注入字数 | 平均耗时 |",
             "|---|---:|---:|---:|---:|---:|"]
    for label, enabled in (("关闭", False), ("开启 C=8/weight=1", True)):
        result = summarize(component_rows(modules, cache, graph, pool, cases, hybrid=enabled))
        lines.append(f"| {label} | {result['final_hits']}/{result['answerable']} | "
                     f"{result['negative_candidate_false_positives']}/{result['negative_context_false_positives']} of {result['negative']} | "
                     f"{result['noise']}/{result['selected']} | {result['injected_chars']/max(result['queries'],1):.2f} | {result['mean_ms']:.3f} ms |")
    return lines + ["", "> Components only; full pipeline verifies disclosure. / 仅测组件，完整管线另行验证披露。"]
