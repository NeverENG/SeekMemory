"""Scoring tests: interval fit, correction gating and hard-failure separation."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.long_horizon.manifest import Checkpoint, Scenario  # noqa: E402
from benchmarks.long_horizon.metrics import (  # noqa: E402
    hard_failures,
    interval_distance,
    interval_fit,
    rollback_score,
    score_checkpoint,
)


def _checkpoint(**overrides) -> Checkpoint:
    values = dict(
        day=30,
        probe="我住在哪？",
        expect_tokens=("杭州",),
        forbid_tokens=("上海",),
        expect_actions=("recall",),
        emotion={"affection": (45.0, 90.0)},
        relationship_bands=("warm", "close"),
    )
    values.update(overrides)
    return Checkpoint(**values)


def _record(**overrides) -> dict:
    values = {
        "day": 30,
        "expected_total": 1,
        "expected_hits": 1,
        "forbidden_total": 1,
        "forbidden_hits": 0,
        "context_forbidden_hits": 0,
        "stale": {"applicable": True, "stale_live": 0, "stale_expired": 1},
        "observed_emotion": {"affection": 50.0},
        "actions": ["recall"],
        "band": "warm",
    }
    values.update(overrides)
    return values


class IntervalTest(unittest.TestCase):
    def test_inside_interval_has_no_distance(self) -> None:
        self.assertEqual(interval_distance(50.0, 45.0, 90.0), 0.0)
        self.assertEqual(interval_fit(50.0, 45.0, 90.0), 1.0)

    def test_outside_interval_decays_to_zero(self) -> None:
        self.assertGreater(interval_distance(20.0, 60.0, 100.0), 0.0)
        self.assertEqual(interval_fit(0.0, 60.0, 100.0), 0.0)
        self.assertAlmostEqual(interval_fit(55.0, 60.0, 100.0), 0.9)


class CheckpointScoreTest(unittest.TestCase):
    def test_all_good_checkpoint_scores_one(self) -> None:
        score = score_checkpoint(_record(), _checkpoint())
        self.assertEqual(score.memory_continuity, 1.0)
        self.assertEqual(score.correction_recovery, 1.0)
        self.assertEqual(score.emotion_trajectory, 1.0)
        self.assertEqual(score.role_action_coherence, 1.0)
        self.assertEqual(score.relationship_boundary, 1.0)
        self.assertEqual(score.notes, ())

    def test_correction_requires_the_new_fact_to_be_present(self) -> None:
        # An empty answer has no stale token, but it also has no corrected fact.
        score = score_checkpoint(
            _record(expected_hits=0, context_forbidden_hits=0, stale={"applicable": False}),
            _checkpoint(),
        )
        self.assertEqual(score.memory_continuity, 0.0)
        self.assertLess(score.correction_recovery, 1.0)
        self.assertIn("corrected_fact_missing", score.notes)

    def test_stale_context_is_reported(self) -> None:
        score = score_checkpoint(_record(context_forbidden_hits=1), _checkpoint())
        self.assertLess(score.correction_recovery, 1.0)
        self.assertIn("stale_fact_in_context", score.notes)

    def test_absent_relationship_state_scores_zero(self) -> None:
        score = score_checkpoint(_record(band=None), _checkpoint())
        self.assertEqual(score.relationship_boundary, 0.0)
        self.assertIn("no_relationship_state", score.notes)

    def test_missing_action_lowers_coherence(self) -> None:
        score = score_checkpoint(_record(actions=["ask"]), _checkpoint())
        self.assertEqual(score.role_action_coherence, 0.0)
        self.assertTrue(any(note.startswith("missing_action") for note in score.notes))

    def test_emotion_out_of_range_is_flagged(self) -> None:
        score = score_checkpoint(_record(observed_emotion={"affection": 20.0}), _checkpoint())
        self.assertLess(score.emotion_trajectory, 1.0)
        self.assertIn("emotion_out_of_range:affection", score.notes)


class RollbackTest(unittest.TestCase):
    def test_restored_then_evolved_scores_one(self) -> None:
        run = {
            "rollbacks": [{"day": 61, "after_revision": 3, "after_origin": "seed"}],
            "persona_history": [{"day": 60, "revision": 2}, {"day": 90, "revision": 6}],
        }
        self.assertEqual(rollback_score(run), 1.0)

    def test_not_re_evolved_scores_half(self) -> None:
        run = {
            "rollbacks": [{"day": 61, "after_revision": 3, "after_origin": "seed"}],
            "persona_history": [{"day": 90, "revision": 3}],
        }
        self.assertEqual(rollback_score(run), 0.5)

    def test_absent_rollback_is_not_applicable(self) -> None:
        self.assertIsNone(rollback_score({"rollbacks": []}))


class HardFailureTest(unittest.TestCase):
    def test_privacy_failure_is_reported_separately(self) -> None:
        runs = [{
            "baseline": "seekmemory",
            "scenario": "privacy_boundary",
            "checkpoints": [{"day": day} for day in (7, 30, 60, 90)],
            "privacy": {"score": 0.0, "events": [{"checkpoint": 7}], "evidence_violations": 0,
                        "persona_prompt_leaks": 0},
        }]
        failures = hard_failures(runs, ["seekmemory"], 4)
        self.assertEqual([item["kind"] for item in failures], ["privacy_or_evidence"])

    def test_missing_baseline_is_reported(self) -> None:
        failures = hard_failures([], ["seekmemory"], 4)
        self.assertEqual(failures[0]["kind"], "missing_baseline")

    def test_short_checkpoint_list_is_reported(self) -> None:
        runs = [{
            "baseline": "seekmemory",
            "scenario": "x",
            "checkpoints": [{"day": 7}],
            "privacy": {"score": 1.0, "events": [], "evidence_violations": 0, "persona_prompt_leaks": 0},
        }]
        failures = hard_failures(runs, ["seekmemory"], 4)
        self.assertEqual(failures[0]["kind"], "missing_checkpoint")


if __name__ == "__main__":
    unittest.main()
