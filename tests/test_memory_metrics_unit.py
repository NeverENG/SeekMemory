"""Check externally meaningful offline metric and acceptance scenarios.

验证离线指标及验收的可观察场景。
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmarks.memory_metrics import accept, observation, summarize


def sample() -> dict:
    """Provide a valid two-query report with one privacy control / 提供含两题及一项隐私对照的合法报告。"""
    rows = [observation("answer", ("target",), ["target"], "target", level_hit=True, retrieved=1),
            observation("negative", (), [], "")]
    return {"schema": 1, "corpus_sha256": "corpus", "evaluator_sha256": "evaluator",
            "config": {"recall_k": 8, "budget_chars": 600}, "clock": "2026-10-30",
            "paths": {"full_pipeline": {"rows": rows}},
            "privacy": [{"id": "private", "passed": True}],
            "retention": {"kept": 1}, "fixture_weight_ratio": 2.0,
            "scale": [{"size": 50, "injected_chars": 100}]}


class MemoryMetricsTest(unittest.TestCase):
    def test_candidate_hit_does_not_imply_final_context_hit(self):
        row = observation("q", ("target",), ["target"], "")
        result = summarize([row])
        self.assertEqual(result["candidate_hits"], 1)
        self.assertEqual(result["final_hits"], 0)

    def test_negative_candidates_and_context_are_counted_separately(self):
        row = observation("q", (), ["irrelevant"], "")
        result = summarize([row])
        self.assertEqual(result["noise"], 1)
        self.assertEqual(result["negative_candidate_false_positives"], 1)
        self.assertEqual(result["negative_context_false_positives"], 0)

    def test_deliberate_regressions_and_missing_evidence_fail(self):
        changes = {
            "hit": lambda r: r["paths"]["full_pipeline"]["rows"][0].update(final_fragments=0),
            "false_positive": lambda r: r["paths"]["full_pipeline"]["rows"][1].update(selected=1, noise=1, chars=5),
            "privacy": lambda r: r["privacy"][0].update(passed=False),
            "source": lambda r: r["paths"]["full_pipeline"]["rows"][0].update(source_leak=True),
            "budget": lambda r: r["paths"]["full_pipeline"]["rows"][0].update(chars=601),
            "limit": lambda r: r["config"].update(budget_chars=900),
            "missing_query": lambda r: r["paths"]["full_pipeline"]["rows"].pop(),
            "missing_privacy": lambda r: r["privacy"].clear(),
            "missing_path": lambda r: r["paths"].clear(),
            "scale": lambda r: r["scale"][0].update(injected_chars=601),
        }
        baseline = sample()
        self.assertTrue(accept(baseline, baseline)["passed"])
        for name, change in changes.items():
            report = deepcopy(baseline)
            change(report)
            with self.subTest(name=name):
                self.assertFalse(accept(report, baseline)["passed"])


if __name__ == "__main__":
    unittest.main()
