"""CLI for the deterministic 7/30/60/90-day benchmark; no network and no real provider.

7/30/60/90 天确定性评测的命令行入口；不访问网络，也不使用真实提供方。

    python -m benchmarks.long_horizon.run
    python -m benchmarks.long_horizon.run --scenario fact_correction --baseline seekmemory
    python -m benchmarks.long_horizon.run --check        # CI: fail on hard failures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

if __package__ in (None, ""):  # pragma: no cover - ``python run.py`` convenience path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.long_horizon import BASELINES, HORIZONS
from benchmarks.long_horizon.harness import SPECS, run_baseline
from benchmarks.long_horizon.manifest import ManifestError, load_manifest
from benchmarks.long_horizon.metrics import aggregate, hard_failures, score_run
from benchmarks.long_horizon.report import build_report, render_markdown, write

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_MANIFEST = REPO / "benchmarks" / "data" / "long_horizon_manifest.json"
DEFAULT_JSON = REPO / "benchmarks" / "results" / "long_horizon.json"
DEFAULT_MD = REPO / "benchmarks" / "results" / "long_horizon.md"


def _parser() -> argparse.ArgumentParser:
    """Build the documented CLI surface / 构造有文档的命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.long_horizon.run",
        description="Deterministic long-horizon persona/relationship benchmark (no network).",
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="seeded scenario manifest")
    parser.add_argument("--out", default=str(DEFAULT_JSON), help="versioned JSON report path")
    parser.add_argument("--md", default=str(DEFAULT_MD), help="Markdown dashboard path")
    parser.add_argument("--baseline", action="append", choices=sorted(SPECS), help="limit to one baseline (repeatable)")
    parser.add_argument("--scenario", action="append", help="limit to one scenario id (repeatable)")
    parser.add_argument("--check", action="store_true", help="exit non-zero on hard failures (CI mode)")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict line")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the benchmark and write both reports; return a process exit code / 运行评测并写出报告，返回退出码。"""
    args = _parser().parse_args(list(argv) if argv is not None else None)
    try:
        manifest = load_manifest(args.manifest)
    except ManifestError as exc:
        print(f"manifest error: {exc}", file=sys.stderr)
        return 2
    known = {scenario.id for scenario in manifest.scenarios}
    unknown = set(args.scenario or ()) - known
    if unknown:
        print(f"unknown scenario(s): {sorted(unknown)}", file=sys.stderr)
        return 2
    scenarios = [scenario for scenario in manifest.scenarios
                 if not args.scenario or scenario.id in set(args.scenario)]
    if not scenarios:
        print(f"no scenario matched: {args.scenario}", file=sys.stderr)
        return 2
    baselines = [name for name in BASELINES if not args.baseline or name in set(args.baseline)]

    scored: list[dict[str, Any]] = []
    for scenario in scenarios:
        for baseline in baselines:
            run = run_baseline(manifest, scenario, baseline)
            result = score_run(run, scenario)
            scored.append(result)
            if not args.quiet:
                print(json.dumps({
                    "scenario": scenario.id,
                    "baseline": baseline,
                    "checkpoints": len(result["checkpoints"]),
                    "dimensions": result["dimensions"],
                    "privacy": result["privacy"]["score"],
                }, ensure_ascii=False))

    dashboard = aggregate(scored)
    failures = hard_failures(scored, baselines, len(HORIZONS))
    report = build_report(manifest, scored, dashboard, failures,
                          scenarios=[scenario.id for scenario in scenarios], baselines=baselines)
    write(report, args.out, args.md)
    verdict = report["verdict"]
    if not args.quiet:
        print(render_markdown(report))
    print(json.dumps({
        "schema": report["schema"],
        "acceptable": verdict["acceptable"],
        "hard_failures": verdict["hard_failures"],
        "result_digest": report["reproducibility"]["result_digest"],
        "json": str(args.out),
        "markdown": str(args.md),
    }, ensure_ascii=False))
    if args.check and not verdict["acceptable"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
