"""Exercise the real offline evaluator CLI, determinism and failure exit status.

验证真实离线评测命令、确定性和失败退出码。
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MemoryBenchmarkTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def run_cli(self, *args, code=None):
        command = [sys.executable, "-X", "utf8", "-B"]
        command += ["-c", code, *map(str, args)] if code else ["benchmarks/run.py", *map(str, args)]
        return subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")

    def test_deterministic_quality_and_immutable_output_paths(self):
        baseline = self.root / "baseline.json"
        first = self.run_cli("--record-baseline", baseline, "--output-dir", self.root / "first")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.run_cli("--baseline", baseline, "--output-dir", self.root / "second")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        reports = [json.loads((self.root / name / "memory.json").read_text(encoding="utf-8")) for name in ("first", "second")]
        for report in reports:
            for result in report["paths"].values():
                result["summary"].pop("mean_ms")
                for row in result["rows"]:
                    row.pop("elapsed_ms")
        self.assertEqual(reports[0], reports[1])
        repeated = self.run_cli("--record-baseline", baseline, "--output-dir", self.root / "third")
        self.assertNotEqual(repeated.returncode, 0)

    def test_real_production_selection_regression_causes_nonzero_status(self):
        baseline = self.root / "baseline.json"
        first = self.run_cli("--record-baseline", baseline, "--output-dir", self.root / "first")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        code = """
from unittest.mock import patch
from benchmarks.run import main
import sys
with patch('recall.score.select', return_value=[]):
    raise SystemExit(main(sys.argv[1:]))
"""
        failed = self.run_cli("--baseline", baseline, "--output-dir", self.root / "mutant", code=code)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        report = json.loads((self.root / "mutant/memory.json").read_text(encoding="utf-8"))
        self.assertFalse(report["acceptance"]["passed"])
        self.assertTrue(any("fragments" in reason for reason in report["acceptance"]["failures"]))

    def test_full_pipeline_privacy_and_budget_regressions_are_rejected(self):
        baseline = self.root / "baseline.json"
        first = self.run_cli("--record-baseline", baseline, "--output-dir", self.root / "first")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        for name, extra in (("privacy", "PROTECTED_SHADOW"), ("budget", "x" * 601)):
            code = f"""
from unittest.mock import patch
from benchmarks.run import main
import recall.pipeline as pipeline
import sys
original = pipeline.query_block
def broken(*args, **kwargs):
    block, info = original(*args, **kwargs)
    return block + {extra!r}, info
with patch.object(pipeline, 'query_block', side_effect=broken):
    raise SystemExit(main(sys.argv[1:]))
"""
            failed = self.run_cli("--baseline", baseline, "--output-dir", self.root / name, code=code)
            self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
            report = json.loads((self.root / name / "memory.json").read_text(encoding="utf-8"))
            self.assertFalse(report["acceptance"]["passed"])
            self.assertTrue(any(name in reason for reason in report["acceptance"]["failures"]))


if __name__ == "__main__":
    unittest.main()
