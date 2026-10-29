"""Evaluate offline memory regression; write new JSON/Markdown artifacts and fail on regression.

执行离线记忆回归，新增 JSON/Markdown 产物，退化时返回失败。
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.memory_corpus import ANCHOR, CONFIG, corpus_digest, to_artifact, _rel_time, _synthetic_pool
from benchmarks.memory_execution import execute
from benchmarks.memory_metrics import accept
from benchmarks.memory_reporting import evaluator_digest, render


def pct(value: float) -> str:
    """Retain the old formatting import / 保留旧格式化导入。"""
    return f"{value * 100:.0f}%"


def revision(repo: Path) -> str:
    """Read Git provenance without accepting a parent checkout's revision / 读取 Git 来源，拒绝误取父目录代码版本。"""
    if not (repo / ".git").exists():
        return "exported-tree"
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def production_digest(repo: Path) -> str:
    """Fingerprint actual evaluated production files / 为实际评测的生产文件计算指纹。"""
    digest = hashlib.sha256()
    for folder in ("core", "app", "services", "store", "perceive", "recall", "maintain"):
        for path in sorted((repo / folder).rglob("*.py")):
            digest.update(path.relative_to(repo).as_posix().encode())
            digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def dirty(repo: Path, *paths: str) -> bool:
    """Record local modifications alongside the actual source hashes / 在实际源码指纹之外记录本地修改状态。"""
    if not (repo / ".git").exists():
        return False
    return bool(subprocess.check_output(
        ["git", "-C", str(repo), "status", "--porcelain", "--", *paths], text=True,
    ).strip())


def main(argv: list[str] | None = None) -> int:
    """Run one target and compare fixed observations with an explicit baseline.

执行一个目标版本，并与明确基线比较固定观察结果。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=ROOT)
    parser.add_argument("--revision", default="", help="Git revision of an explicitly exported source tree")
    parser.add_argument("--baseline", type=Path, default=ROOT / "benchmarks/data/memory_baseline.json")
    parser.add_argument("--record-baseline", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.revision and (repo / ".git").exists():
        parser.error("--revision is only for explicitly exported source trees")
    if args.record_baseline and args.record_baseline.exists():
        parser.error("baseline already exists; choose a new snapshot path")
    report = {"schema": 1, "clock": ANCHOR.isoformat(), "config": dict(CONFIG),
              "corpus_sha256": corpus_digest(), "evaluator_sha256": evaluator_digest(),
              "provenance": {"code_revision": args.revision or revision(repo),
                             "production_sha256": production_digest(repo),
                             "production_dirty": dirty(repo, "core", "app", "services", "store", "perceive", "recall", "maintain"),
                             "evaluator_revision": revision(ROOT),
                             "evaluator_dirty": dirty(ROOT, "benchmarks"),
                             "python": platform.python_version(), "platform": sys.platform},
              **execute(repo)}
    if args.record_baseline:
        report["acceptance"] = accept(report, report)
    else:
        report["acceptance"] = accept(report, json.loads(args.baseline.read_text(encoding="utf-8")))
    folder = args.output_dir or ROOT / ".tmp/benchmarks" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    (folder / "memory.json").write_text(text, encoding="utf-8")
    (folder / "memory.md").write_text(render(report), encoding="utf-8")
    if args.record_baseline and report["acceptance"]["passed"]:
        args.record_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.record_baseline.write_text(text, encoding="utf-8")
    print(json.dumps({"acceptance": report["acceptance"], "output": str(folder)}, ensure_ascii=False))
    return 0 if report["acceptance"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
