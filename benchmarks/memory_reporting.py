"""Render aggregate offline observations without modifying historical reports.

渲染离线聚合观察，不修改历史报告。
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def evaluator_digest() -> str:
    """Hash all evaluator inputs, excluding generated baselines / 为全部评测输入计算指纹，排除生成的基线。"""
    root = Path(__file__).parent
    names = ("run.py", "dataset.py", "memory_corpus.py", "memory_execution.py",
             "memory_metrics.py", "memory_reporting.py", "memory_target.py", "retrieval_compare.py")
    digest = hashlib.sha256()
    for name in names:
        digest.update(name.encode())
        digest.update((root / name).read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def render(report: dict) -> str:
    """Describe measured counts and limitations, without a personality composite.

说明实测计数及限制，不生成综合人格分数。
    """
    lines = ["# Offline memory regression / 离线记忆回归", "",
             f"Acceptance / 验收: **{'PASS' if report['acceptance']['passed'] else 'FAIL'}**", "",
             "Synthetic fixtures; no real model, host or online-cost measurement. / 合成样本，不测真实模型、宿主或线上费用。", "",
             f"Code / 代码: `{report['provenance']['code_revision']}`",
             f"Evaluator / 评测器: `{report['evaluator_sha256']}`",
             f"Corpus / 语料: `{report['corpus_sha256']}`", "",
             "| Path / 路径 | Candidate hits / 候选命中 | Context hits / 上下文命中 | Negative false positives (candidate/context) / 无答案误召回 | Noise / 噪声 | Mean injected chars / 平均注入字数 | Mean ms / 平均毫秒 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name, result in report["paths"].items():
        s = result["summary"]
        lines.append(f"| {name} | {s['candidate_hits']}/{s['answerable']} | {s['final_hits']}/{s['answerable']} | "
                     f"{s['negative_candidate_false_positives']}/{s['negative_context_false_positives']} of {s['negative']} | "
                     f"{s['noise']}/{s['selected']} | {s['injected_chars']/max(s['queries'],1):.2f} | {s['mean_ms']:.3f} |")
    lines += ["", "Noise includes every candidate selected for no-answer queries. Candidate hits do not establish injection. / 无答案题选中项全部计入噪声，候选命中不代表已注入。",
              "Only full_pipeline evaluates disclosure; component rows are retrieval/assembly measurements. / 只有 full_pipeline 包含披露，组件行仅测检索及组装。",
              "Character counts are not tokenizer counts; timing depends on the machine. / 字数不是模型 token 数，耗时依赖机器。", "",
              f"Fixture-weight ratio / 样本预设权重比: **{report['fixture_weight_ratio']:.3f}×** (does not execute reinforce / 不执行强化函数)",
              f"Retention samples / 留存样本: `{report['retention']}` (does not execute nightly maintenance / 不执行夜间维护)",
              f"Privacy and positive controls / 隐私及正常披露正例: {sum(x['passed'] for x in report['privacy'])}/{len(report['privacy'])}", "",
              "The old human-likeness composite is historical and is not an acceptance criterion. / 旧综合人格分数仅属历史，不作为验收标准。", "",
              "| Memories / 记忆数 | Full chars / 全量字数 | Injected chars / 注入字数 |",
              "|---|---:|---:|"]
    lines += [f"| {row['size']} | {row['full_chars']} | {row['injected_chars']} |" for row in report["scale"]]
    if report["acceptance"]["failures"]:
        lines += ["", "Failures / 失败: " + ", ".join(report["acceptance"]["failures"])]
    return "\n".join(lines) + "\n"
