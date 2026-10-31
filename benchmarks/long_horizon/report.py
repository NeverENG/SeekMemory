"""Render versioned JSON and a Markdown dimension dashboard; no fixture text is ever written.

输出带版本的 JSON 与 Markdown 分维成绩单；绝不写入场景正文或私聊内容。

The report deliberately stores counters, booleans and hashes instead of response or
context text: a leaked report would otherwise become a second copy of private
material.  A single "human-likeness" total is not produced, and the verdict only
reports whether the *benchmark* ran correctly; dimension values are information for
reviewers, not a release gate.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import ACTOR_VERSION, BASELINES, DIMENSIONS, PACKAGE_VERSION, REPORT_SCHEMA
from .manifest import Manifest, fingerprint

CAVEATS = (
    "合成场景 + 假模型适配器的确定性运行，不代表真实模型质量，也不能证明人类级人格表现。",
    "分维成绩是回归代理；可另做盲评验证与人的感受是否相关，本期不包含。",
    "秘密泄漏与伪造证据是硬失败，其他维度的高分不能抵消。",
    "fake_simulated 用量由字数估算，不是计费 token；缺失用量不当作零。",
)

_DIMENSION_LABELS = {
    "memory_continuity": "记忆连续",
    "correction_recovery": "纠错/回滚恢复",
    "emotion_trajectory": "情绪轨迹区间",
    "role_action_coherence": "角色/行动一致",
    "relationship_boundary": "关系边界",
    "privacy_evidence": "隐私/证据",
    "efficiency": "效率（不评分）",
}


def harness_digest() -> str:
    """Hash every harness module so a report can be tied to its code / 对评测代码做指纹，便于报告溯源。"""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in ("__init__.py", "adapter.py", "clock.py", "harness.py", "manifest.py",
                 "metrics.py", "report.py", "run.py"):
        path = root / name
        if path.exists():
            digest.update(name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _strip_timing(value: Any) -> Any:
    """Remove machine-dependent fields before hashing for reproducibility.

    在计算可复现指纹前移除与机器相关的字段。
    """
    if isinstance(value, dict):
        return {
            key: _strip_timing(item)
            for key, item in value.items()
            if key not in ("elapsed_ms", "generated_at", "platform", "python")
        }
    if isinstance(value, list):
        return [_strip_timing(item) for item in value]
    return value


def _canonical(value: Any) -> str:
    """Serialize deterministically for the reproducibility digest / 为可复现指纹做确定性序列化。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_report(
    manifest: Manifest,
    results: Sequence[Mapping[str, Any]],
    dashboard: Mapping[str, Any],
    failures: Sequence[Mapping[str, Any]],
    *,
    scenarios: Sequence[str],
    baselines: Sequence[str] = BASELINES,
) -> dict[str, Any]:
    """Assemble the versioned report object / 组装带版本的报告对象。"""
    payload = {
        "schema": REPORT_SCHEMA,
        "package_version": PACKAGE_VERSION,
        "actor_version": ACTOR_VERSION,
        "harness_sha256": harness_digest(),
        "generated_at": _now(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "manifest": fingerprint(manifest),
        "horizons": list(manifest.horizons),
        "baselines": list(baselines),
        "scenarios": list(scenarios),
        "dimensions": list(DIMENSIONS),
        "results": list(results),
        "dashboard": dict(dashboard),
        "hard_failures": list(failures),
        "usage_provenance": {
            "model": "fake_simulated",
            "provider": "deterministic-recorded",
            "caveat": "所有 token 数由字数估算并标记为 fake_simulated，不是提供方上报值。",
            "vocabulary": {
                "provider_reported": "提供方返回的真实用量；本期不存在。",
                "fake_simulated": "假模型按字数估算的确定性用量，只用于同版本内比较。",
                "estimated": "有依据但非提供方上报的估算；本期不产生。",
                "unavailable": "该 baseline 根本没有这个阶段，缺失不当作零。",
            },
        },
        "caveats": list(CAVEATS),
    }
    payload["reproducibility"] = {
        "seed": manifest.seed,
        "manifest_digest": manifest.digest,
        "harness_sha256": payload["harness_sha256"],
        "result_digest": hashlib.sha256(_canonical(_strip_timing(payload["results"])).encode("utf-8")).hexdigest(),
    }
    payload["verdict"] = {
        "acceptable": not failures,
        "hard_failures": len(failures),
        "note": "只表示评测自身跑通且没有硬失败；不代表 SeekMemory 达到人类级人格质量。",
    }
    return payload


def _now() -> str:
    """Read the wall clock once, for provenance only / 仅用于溯源地读取一次真实时间。"""
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def _fmt(value: Any) -> str:
    """Format one dashboard cell without inventing precision / 格式化一个看板单元格，不虚构精度。"""
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the Markdown dimension dashboard / 渲染 Markdown 分维成绩单。"""
    manifest = report.get("manifest") or {}
    lines: list[str] = []
    lines.append("# SeekMemory 长周期（7/30/60/90 天）人格与情绪/关系评测")
    lines.append("")
    lines.append(
        "> 合成场景 + 假模型适配器的确定性运行，**不是**真实模型质量或线上指标。"
        "分维成绩只作为回归代理，硬失败（隐私/证据）不能由其他维度抵消。"
    )
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| schema | `{report.get('schema')}` |")
    lines.append(f"| 包版本 | `{report.get('package_version')}` |")
    lines.append(f"| 表演模型 | `{report.get('actor_version')}` |")
    lines.append(f"| 清单指纹 | `{manifest.get('digest')}` |")
    lines.append(f"| 随机种子 | `{manifest.get('seed')}` |")
    lines.append(f"| 场景 | {', '.join(report.get('scenarios') or [])} |")
    lines.append(f"| baseline | {', '.join(report.get('baselines') or [])} |")
    lines.append(f"| 运行时间 | {report.get('generated_at')} |")
    lines.append("")
    lines.append("## 分维成绩单")
    lines.append("")
    header = "| baseline | " + " | ".join(_DIMENSION_LABELS[name] for name in DIMENSIONS) + " | 检查点 | tokens/检查点 |"
    lines.append(header)
    lines.append("|" + "---|" * (len(DIMENSIONS) + 3))
    dashboard = report.get("dashboard") or {}
    for baseline, entry in dashboard.items():
        values = [entry.get("dimensions", {}).get(name) for name in DIMENSIONS]
        cells = " | ".join(_fmt(value) for value in values)
        lines.append(f"| {baseline} | {cells} | {entry.get('checkpoints')} | {entry.get('tokens_per_checkpoint')} |")
    lines.append("")
    lines.append("## 逐场景检查点")
    lines.append("")
    lines.append("| 场景 | baseline | 检查点 | 记忆连续 | 纠错/回滚 | 情绪区间 | 角色/行动 | 关系边界 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for run in report.get("results") or ():
        for checkpoint in run.get("checkpoints") or ():
            lines.append(
                f"| {run.get('scenario')} | {run.get('baseline')} | {checkpoint.get('day')} | "
                f"{_fmt(checkpoint.get('memory_continuity'))} | {_fmt(checkpoint.get('correction_recovery'))} | "
                f"{_fmt(checkpoint.get('emotion_trajectory'))} | {_fmt(checkpoint.get('role_action_coherence'))} | "
                f"{_fmt(checkpoint.get('relationship_boundary'))} |"
            )
    lines.append("")
    lines.append("## 情绪轨迹")
    lines.append("")
    lines.append("| 场景 | baseline | 信号 | 观测序列 | 目标区间 | 平均区间差距 | 方向一致 |")
    lines.append("|---|---|---|---|---|---|---|")
    for run in report.get("results") or ():
        for signal, trajectory in (run.get("trajectory") or {}).items():
            observed = ", ".join(_fmt(item) for item in trajectory.get("observed") or [])
            targets = "; ".join(f"{_fmt(low)}–{_fmt(high)}" for low, high in trajectory.get("targets") or [])
            lines.append(
                f"| {run.get('scenario')} | {run.get('baseline')} | {signal} | {observed} | "
                f"{targets} | {_fmt(trajectory.get('mean_interval_gap'))} | {_fmt(trajectory.get('direction_matches'))} |"
            )
    lines.append("")
    lines.append("## 用量来源")
    lines.append("")
    lines.append("来源词表：`provider_reported`（提供方上报，本期不存在）、`fake_simulated`（假模型按字数估算）、"
                 "`estimated`（非提供方估算）、`unavailable`（该 baseline 没有这个阶段，缺失不当作零）。")
    lines.append("")
    lines.append("| baseline | 阶段 | 调用 | 输入 tokens | 缓存输入 | 输出 tokens | 来源 |")
    lines.append("|---|---|---|---|---|---|---|")
    for baseline, entry in dashboard.items():
        runs = [run for run in report.get("results") or () if run.get("baseline") == baseline]
        stages: dict[str, dict[str, int]] = {}
        for run in runs:
            for name, usage in (run.get("usage") or {}).items():
                bucket = stages.setdefault(name, {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0,
                                                  "output_tokens": 0, "provenance": usage.get("provenance")})
                for key in ("calls", "input_tokens", "cached_input_tokens", "output_tokens"):
                    bucket[key] = int(bucket.get(key, 0)) + int(usage.get(key) or 0)
        for name, usage in stages.items():
            lines.append(
                f"| {baseline} | {name} | {usage['calls']} | {usage['input_tokens']} | "
                f"{usage['cached_input_tokens']} | {usage['output_tokens']} | `{usage.get('provenance')}` |"
            )
    lines.append("")
    lines.append("## 生命周期节点")
    lines.append("")
    lines.append("| baseline | 场景 | 重启次数 | 回滚次数 | 回滚后来源 | 回滚评分 |")
    lines.append("|---|---|---|---|---|---|")
    for run in report.get("results") or ():
        rollbacks = run.get("rollbacks") or []
        origins = ", ".join(str(item.get("after_origin")) for item in rollbacks) or "—"
        lines.append(
            f"| {run.get('baseline')} | {run.get('scenario')} | {run.get('restarts')} | "
            f"{len(rollbacks)} | {origins} | {_fmt(run.get('rollback_score'))} |"
        )
    lines.append("")
    lines.append("## 一次纠偏（可选）")
    lines.append("")
    lines.append("只对卡片预先声明的检查点，从同一份上下文与人格快照复跑一次；"
                 "自然成绩保持第一轮原样，干预不能掩盖失败。")
    lines.append("")
    lines.append("| baseline | 场景 | 尝试 | 自然已合规 | 自然回避 | 恢复 | 过度纠偏 | 隐私违规 | 额外 tokens |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for run in report.get("results") or ():
        steering = run.get("steering") or {}
        if not steering.get("attempted"):
            continue
        lines.append(
            f"| {run.get('baseline')} | {run.get('scenario')} | {steering.get('attempted')} | "
            f"{steering.get('natural_compliant')} | {steering.get('withheld_naturally')} | "
            f"{steering.get('recovered')} | {steering.get('overcorrected')} | "
            f"{steering.get('privacy_hits')} | {steering.get('extra_tokens')} |"
        )
    lines.append("")
    lines.append("## 硬失败")
    lines.append("")
    failures = report.get("hard_failures") or []
    if not failures:
        lines.append("无。（隐私、证据、检查点完整性与基线覆盖全部通过。）")
    else:
        lines.append("| 类型 | baseline | 场景 | 细节 |")
        lines.append("|---|---|---|---|")
        for failure in failures:
            detail = ", ".join(f"{key}={value}" for key, value in failure.items()
                               if key not in ("kind", "baseline", "scenario"))
            lines.append(f"| {failure.get('kind')} | {failure.get('baseline')} | {failure.get('scenario') or '—'} | {detail} |")
    lines.append("")
    lines.append("## 复现")
    lines.append("")
    lines.append("```bash")
    lines.append("python -m benchmarks.long_horizon.run --out benchmarks/results/long_horizon.json \\")
    lines.append("    --md benchmarks/results/long_horizon.md")
    lines.append("```")
    lines.append("")
    lines.append(f"结果指纹：`{(report.get('reproducibility') or {}).get('result_digest')}`")
    lines.append("")
    lines.append("同一种子与同一包版本应得到相同结果指纹；报告区分 `fake_simulated`、`provider_reported`、")
    lines.append("`estimated`、`unavailable` 四种用量来源。")
    lines.append("")
    return "\n".join(lines)


def write(report: Mapping[str, Any], json_path: str | Path | None, md_path: str | Path | None) -> None:
    """Write JSON and Markdown outputs, creating parent directories / 写出 JSON 与 Markdown，必要时创建目录。"""
    if json_path:
        path = Path(json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if md_path:
        path = Path(md_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")


__all__ = ["build_report", "render_markdown", "write", "harness_digest", "CAVEATS"]
