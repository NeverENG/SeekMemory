"""End-to-end tests: the deterministic 7/30/60/90 run, reproducibility and privacy of the report."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.long_horizon import BASELINES, HORIZONS  # noqa: E402
from benchmarks.long_horizon.manifest import load_manifest  # noqa: E402
from benchmarks.long_horizon.run import main  # noqa: E402

MANIFEST = ROOT / "benchmarks" / "data" / "long_horizon_manifest.json"


class long_horizon_run:
    """Run the CLI into a temporary directory and return the decoded report.

    在临时目录运行命令行并返回解析后的报告。
    """

    def __init__(self, *extra: str) -> None:
        self.extra = list(extra)

    def __enter__(self) -> dict:
        self.temp = tempfile.TemporaryDirectory(prefix="seekmemory_lh_test_")
        self.json_path = Path(self.temp.name) / "report.json"
        self.md_path = Path(self.temp.name) / "report.md"
        code = main([
            "--manifest", str(MANIFEST),
            "--out", str(self.json_path),
            "--md", str(self.md_path),
            "--quiet",
            *self.extra,
        ])
        if code != 0:
            raise AssertionError(f"benchmark exited {code}")
        self.report = json.loads(self.json_path.read_text(encoding="utf-8"))
        self.markdown = self.md_path.read_text(encoding="utf-8")
        return self.report

    def __exit__(self, *_exc) -> None:
        self.temp.cleanup()


class FullRunTest(unittest.TestCase):
    def test_full_suite_runs_every_baseline_and_horizon(self) -> None:
        with long_horizon_run() as report:
            self.assertTrue(report["verdict"]["acceptable"], report["hard_failures"])
            self.assertEqual(report["hard_failures"], [])
            self.assertEqual(report["baselines"], list(BASELINES))
            results = report["results"]
            self.assertEqual(len(results), len(BASELINES) * len(report["scenarios"]))
            for run in results:
                self.assertEqual([item["day"] for item in run["checkpoints"]], list(HORIZONS))
                self.assertTrue(run["checkpoints"])

    def test_seekmemory_beats_floor_baseline_on_continuity(self) -> None:
        with long_horizon_run() as report:
            dashboard = report["dashboard"]
            self.assertGreater(
                dashboard["seekmemory"]["dimensions"]["memory_continuity"],
                dashboard["no-memory"]["dimensions"]["memory_continuity"],
            )
            self.assertGreater(
                dashboard["seekmemory"]["dimensions"]["role_action_coherence"],
                dashboard["no-memory"]["dimensions"]["role_action_coherence"],
            )
            self.assertGreater(
                dashboard["seekmemory"]["dimensions"]["relationship_boundary"],
                dashboard["seekmemory-nomaint"]["dimensions"]["relationship_boundary"],
            )

    def test_persona_revision_and_rollback_are_exercised(self) -> None:
        with long_horizon_run() as report:
            run = next(
                item for item in report["results"]
                if item["baseline"] == "seekmemory" and item["scenario"] == "fact_correction"
            )
            revisions = [item["revision"] for item in run["persona_history"]]
            self.assertGreater(max(revisions), 1)
            rollbacks = [item for item in run["rollbacks"] if not item.get("skipped")]
            self.assertTrue(rollbacks, "rollback milestone must actually roll back")
            self.assertEqual(rollbacks[0]["after_origin"], "seed")
            self.assertIsNotNone(run["rollback_score"])
            self.assertEqual(run["memory_final"]["broken_sources"], 0)

    def test_restart_milestones_keep_memory_readable(self) -> None:
        with long_horizon_run() as report:
            run = next(
                item for item in report["results"]
                if item["baseline"] == "seekmemory" and item["scenario"] == "recurring_gym_plan"
            )
            self.assertEqual(run["restarts"], 2)
            after = [item for item in run["checkpoints"] if item["day"] >= 60]
            self.assertTrue(after)
            for checkpoint in after:
                self.assertEqual(checkpoint["memory_continuity"], 1.0)
                self.assertGreater(checkpoint["memory"]["active"], 0)
            floor = next(
                item for item in report["results"]
                if item["baseline"] == "no-memory" and item["scenario"] == "recurring_gym_plan"
            )
            self.assertEqual(floor["restarts"], 0)

    def test_usage_is_labelled_fake_simulated_and_need_not_be_zero(self) -> None:
        with long_horizon_run() as report:
            stage = next(
                run for run in report["results"]
                if run["baseline"] == "seekmemory" and run["scenario"] == "recurring_gym_plan"
            )["usage"]["extraction"]
            self.assertEqual(stage["provenance"], "fake_simulated")
            self.assertGreater(stage["calls"], 0)
            floor = next(
                run for run in report["results"]
                if run["baseline"] == "no-memory" and run["scenario"] == "recurring_gym_plan"
            )["usage"]
            self.assertEqual(floor["extraction"]["provenance"], "unavailable")


class ReproducibilityTest(unittest.TestCase):
    def test_same_seed_produces_the_same_result_digest(self) -> None:
        with long_horizon_run("--scenario", "fact_correction", "--baseline", "seekmemory") as first:
            digest = first["reproducibility"]["result_digest"]
        with long_horizon_run("--scenario", "fact_correction", "--baseline", "seekmemory") as second:
            self.assertEqual(digest, second["reproducibility"]["result_digest"])


class ReportPrivacyTest(unittest.TestCase):
    def test_report_contains_no_fixture_text(self) -> None:
        manifest = load_manifest(MANIFEST)
        markers = {
            value
            for scenario in manifest.scenarios
            for value in scenario.tokens.values()
        }
        markers.update(
            turn.text
            for scenario in manifest.scenarios
            for event in scenario.events
            for turn in event.turns
        )
        self.assertTrue(markers)
        runner = long_horizon_run("--scenario", "privacy_boundary", "--baseline", "seekmemory")
        with runner as report:
            payload = json.dumps(report, ensure_ascii=False)
            for marker in markers:
                self.assertNotIn(marker, payload, f"fixture text leaked into JSON: {marker[:12]}")
                self.assertNotIn(marker, runner.markdown, f"fixture text leaked into Markdown: {marker[:12]}")
            for checkpoint in report["results"][0]["checkpoints"]:
                self.assertNotIn("text", checkpoint)
                self.assertIn("response_sha", checkpoint)


class CheckModeTest(unittest.TestCase):
    def test_check_mode_passes_and_reports_verdict(self) -> None:
        with long_horizon_run("--check", "--scenario", "privacy_boundary") as report:
            self.assertTrue(report["verdict"]["acceptable"])
            self.assertEqual(report["schema"], "seekmemory.long_horizon.v1")
            self.assertEqual(report["actor_version"], "lh-actor-v1")


class OneTakeCorrectionTest(unittest.TestCase):
    """The optional steered pass can only override withholding, never invent evidence.

    可选纠偏只能覆盖“回避提起”，不能凭空造出上下文里没有的证据。
    """

    CUES = {"affection": {"low": ("低调陈述", 20), "mid": ("中调陈述", 50), "high": ("高调陈述", 80)}}
    ACTIONS = {"recall": "我记得{tok}。", "repair": "上次是我说重了。", "ask": "这件事我没有记录。"}

    def _perform(self, *, context: str, band: str, correction: bool):
        from benchmarks.long_horizon.adapter import ScriptedActor, UsageLedger

        actor = ScriptedActor(UsageLedger())
        return actor.perform(
            probe="你还记得吗？",
            context=context,
            persona_text="你是阿岚。",
            tokens={"unresolved": "生气"},
            cues=self.CUES,
            actions=self.ACTIONS,
            band=band,
            correction=correction,
        )

    def test_withholding_is_visible_and_correction_recovers(self) -> None:
        natural = self._perform(context="他当时很生气", band="dislike", correction=False)
        self.assertTrue(natural.withheld)
        self.assertEqual(natural.actions, ("ask",))
        self.assertNotIn("生气", natural.text)
        steered = self._perform(context="他当时很生气", band="dislike", correction=True)
        self.assertFalse(steered.withheld)
        self.assertIn("recall", steered.actions)
        self.assertIn("生气", steered.text)

    def test_correction_cannot_invent_missing_evidence(self) -> None:
        steered = self._perform(context="", band="dislike", correction=True)
        self.assertEqual(steered.actions, ("ask",))
        self.assertNotIn("recall", steered.actions)


if __name__ == "__main__":
    unittest.main()
