"""Pure capacity actions and configuration decisions.

纯容量动作及配置决策。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
from unittest.mock import patch
from core.capacity import (
    NORMAL, PRESSURED, PROTECTIVE, SATURATED,
    CapacityGovernor, CapacitySnapshot, load_thresholds,
)

class CapacityGovernorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = CapacityGovernor()

    def test_normal_queue_schedules_work(self) -> None:
        decision = self.governor.evaluate(CapacitySnapshot(pending_rows=1))
        self.assertEqual(decision.state, NORMAL)
        self.assertEqual(decision.actions, ("schedule_extraction",))

    def test_pending_pressure_raises_batch_size(self) -> None:
        decision = self.governor.evaluate(CapacitySnapshot(pending_rows=80))
        self.assertEqual(decision.state, PRESSURED)
        self.assertIn("raise_batch_size", decision.actions)

    def test_artifact_and_pending_hard_limits_saturate(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(pending_rows=200, artifact_count=800)
        )
        self.assertEqual(decision.state, SATURATED)
        self.assertIn("backpressure", decision.actions)
        self.assertIn("compact_artifacts", decision.actions)
        self.assertIn("forget_expired", decision.actions)

    def test_context_and_trace_pressure_trigger_actions(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(context_chars_per_turn=4000, trace_rows=450)
        )
        self.assertEqual(decision.state, SATURATED)
        self.assertIn("degrade_recall", decision.actions)
        self.assertIn("trim_trace", decision.actions)

    def test_trace_age_has_a_soft_stage_before_trimming(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(trace_oldest_age_seconds=4 * 24 * 60 * 60)
        )
        self.assertEqual(decision.state, PRESSURED)
        self.assertNotIn("trim_trace", decision.actions)

    def test_pressure_reports_a_numeric_level(self) -> None:
        calm = self.governor.evaluate(CapacitySnapshot(pending_rows=1))
        self.assertLess(calm.pressure, 0.1)
        full = self.governor.evaluate(CapacitySnapshot(pending_rows=200))
        self.assertGreaterEqual(full.pressure, 0.99)
        self.assertLessEqual(full.pressure, 1.0)

    def test_thresholds_accept_mapping_and_env_overrides(self) -> None:
        limits = load_thresholds({"pending_saturated_rows": 5, "unknown": "x"})
        self.assertEqual(limits.pending_saturated_rows, 5)
        self.assertEqual(limits.pending_pressured_rows, 80)
        with patch.dict(
            os.environ, {"SEEKMEMORY_CAPACITY_PENDING_SATURATED_ROWS": "7"}
        ):
            self.assertEqual(load_thresholds().pending_saturated_rows, 7)
        self.assertEqual(
            load_thresholds({"pending_saturated_rows": "bad"}).pending_saturated_rows,
            200,
        )

    def test_protective_state_exposes_every_alert_action(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(
                source_bytes=1024 * 1024 * 1024,
                pending_rows=401,
                artifact_count=801,
            )
        )
        self.assertEqual(decision.state, PROTECTIVE)
        self.assertEqual(
            set(decision.actions),
            {
                "schedule_extraction",
                "raise_batch_size",
                "backpressure",
                "compact_artifacts",
                "forget_expired",
                "alert",
            },
        )

    def test_all_eight_actions_are_reachable(self) -> None:
        snapshots = [
            CapacitySnapshot(pending_rows=1),
            CapacitySnapshot(pending_rows=80),
            CapacitySnapshot(pending_rows=200),
            CapacitySnapshot(artifact_count=400),
            CapacitySnapshot(artifact_count=800),
            CapacitySnapshot(context_chars_per_turn=4000),
            CapacitySnapshot(trace_rows=450),
            CapacitySnapshot(pending_rows=400, source_bytes=1024 * 1024 * 1024),
        ]
        actions = set()
        for snapshot in snapshots:
            actions.update(self.governor.evaluate(snapshot).actions)
        self.assertEqual(
            actions,
            {
                "schedule_extraction",
                "raise_batch_size",
                "backpressure",
                "compact_artifacts",
                "forget_expired",
                "degrade_recall",
                "trim_trace",
                "alert",
            },
        )


class CapacityGovernorV2Test(unittest.TestCase):
    def setUp(self) -> None:
        self.governor = CapacityGovernor()

    def test_deferred_headroom_releases_work(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(pending_rows=10, deferred_rows=10)
        )
        self.assertIn("release_deferred", decision.actions)
        self.assertEqual(decision.state, NORMAL)

    def test_deferred_pressure_does_not_release_more(self) -> None:
        decision = self.governor.evaluate(CapacitySnapshot(deferred_rows=200))
        self.assertEqual(decision.state, PRESSURED)
        self.assertNotIn("release_deferred", decision.actions)

    def test_dead_rows_raise_alert(self) -> None:
        decision = self.governor.evaluate(CapacitySnapshot(dead_rows=10))
        self.assertIn("alert", decision.actions)
        self.assertIn("dead:10rows", decision.reasons)

    def test_database_size_raises_pressure(self) -> None:
        decision = self.governor.evaluate(
            CapacitySnapshot(db_bytes=1024 * 1024 * 1024)
        )
        self.assertEqual(decision.state, SATURATED)
        self.assertIn("database:", " ".join(decision.reasons))


if __name__ == "__main__":
    unittest.main()
