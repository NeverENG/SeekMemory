"""Measure observations and reject quality regressions without production I/O.

仅计算观察指标和退化判定，不执行生产读写。
"""

from __future__ import annotations


def observation(query_id: str, expected: tuple[str, ...], texts: list[str], block: str,
                *, level_hit: bool = False, chars_limit: int = 600,
                retrieved: int = 0, elapsed_ms: float = 0.0) -> dict:
    """Keep candidate evidence distinct from final model context / 区分候选证据与最终模型上下文。"""
    wanted = tuple(term.lower() for term in expected)
    candidate_text = " ".join(texts).lower()
    final_text = block.lower()
    return {"id": query_id, "expected": len(wanted),
            "candidate_fragments": sum(term in candidate_text for term in wanted),
            "final_fragments": sum(term in final_text for term in wanted),
            "selected": len(texts), "retrieved": retrieved,
            "noise": sum(not any(term in text.lower() for term in wanted) for text in texts),
            "level_hit": int(level_hit), "chars": len(block), "chars_limit": chars_limit,
            "elapsed_ms": elapsed_ms}


def summarize(rows: list[dict]) -> dict:
    """Count no-answer noise too; character counts are not token counts.

无答案题也计入噪声；字数不是模型 token 数。
    """
    answerable = [row for row in rows if row["expected"]]
    negative = [row for row in rows if not row["expected"]]
    return {"queries": len(rows), "answerable": len(answerable), "negative": len(negative),
            "candidate_hits": sum(row["candidate_fragments"] > 0 for row in answerable),
            "final_hits": sum(row["final_fragments"] > 0 for row in answerable),
            "negative_candidate_false_positives": sum(row["selected"] > 0 for row in negative),
            "negative_context_false_positives": sum(row["chars"] > 0 for row in negative),
            "noise": sum(row["noise"] for row in rows), "selected": sum(row["selected"] for row in rows),
            "injected_chars": sum(row["chars"] for row in rows),
            "max_chars": max((row["chars"] for row in rows), default=0),
            "mean_ms": sum(row["elapsed_ms"] for row in rows) / max(len(rows), 1)}


def accept(current: dict, baseline: dict) -> dict:
    """Use the same evaluator and inputs; latency and legacy composites are not gates.

使用同一评测器及输入；耗时和旧综合分不作为门槛。
    """
    failures = []
    for key in ("schema", "corpus_sha256", "evaluator_sha256", "config", "clock"):
        if current.get(key) != baseline.get(key):
            failures.append(f"incompatible_{key}")
    if set(current.get("paths", {})) != set(baseline.get("paths", {})) or not current.get("paths"):
        failures.append("path_coverage")
    for path, previous in baseline.get("paths", {}).items():
        actual = current.get("paths", {}).get(path, {})
        old_rows = {row["id"]: row for row in previous.get("rows", [])}
        new_rows = {row["id"]: row for row in actual.get("rows", [])}
        if not old_rows or set(old_rows) != set(new_rows):
            failures.append(f"{path}:query_coverage")
            continue
        for identity, old in old_rows.items():
            row = new_rows[identity]
            if row["expected"] != old["expected"]:
                failures.append(f"{path}:{identity}:annotations")
            for metric in ("candidate_fragments", "final_fragments", "level_hit"):
                if row[metric] < old[metric]:
                    failures.append(f"{path}:{identity}:{metric}")
            if row["chars_limit"] != old["chars_limit"] or row["chars"] > row["chars_limit"] or row["retrieved"] > current["config"]["recall_k"]:
                failures.append(f"{path}:{identity}:budget")
            if row.get("source_leak"):
                failures.append(f"{path}:{identity}:source_leak")
        old_summary, summary = summarize(list(old_rows.values())), summarize(list(new_rows.values()))
        for metric in ("negative_candidate_false_positives", "negative_context_false_positives", "noise"):
            if summary[metric] > old_summary[metric]:
                failures.append(f"{path}:{metric}")
        if summary["noise"] * max(old_summary["selected"], 1) > old_summary["noise"] * max(summary["selected"], 1):
            failures.append(f"{path}:noise_ratio")
    old_privacy = {row["id"] for row in baseline.get("privacy", [])}
    if not old_privacy or old_privacy != {row["id"] for row in current.get("privacy", [])}:
        failures.append("privacy_coverage")
    if any(not row["passed"] for row in current.get("privacy", [])):
        failures.append("privacy_or_positive_control")
    if current.get("retention") != baseline.get("retention"):
        failures.append("retention_samples")
    if current.get("fixture_weight_ratio") != baseline.get("fixture_weight_ratio"):
        failures.append("fixture_weight_ratio")
    old_scale = {row["size"] for row in baseline.get("scale", [])}
    if not old_scale or old_scale != {row["size"] for row in current.get("scale", [])}:
        failures.append("scale_coverage")
    if any(row["injected_chars"] > current["config"]["budget_chars"] for row in current.get("scale", [])):
        failures.append("scale_budget")
    return {"passed": not failures, "failures": failures}
