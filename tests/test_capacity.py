"""CapacityGovernor decisions and Source-backed extraction queue tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.capacity import (  # noqa: E402
    NORMAL,
    PRESSURED,
    PROTECTIVE,
    SATURATED,
    CapacityGovernor,
    CapacitySnapshot,
    load_thresholds,
)
from core.artifact import make  # noqa: E402
from core.source import Source  # noqa: E402
from perceive.buffer import Buffer  # noqa: E402
from store.db import DB  # noqa: E402
from webui.journal import Journal  # noqa: E402


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


class ExtractionProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = DB(os.path.join(self.temp.name, "memory.db"))

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_pending_projection_is_rebuilt_from_source_and_state(self) -> None:
        source = Source(
            "s1", "turn1", "umo:a", "u1", "user", "remember this", "2026-10-22T12:00:00"
        )
        buffer = Buffer(os.path.join(self.temp.name, "pending.json"), db=self.db)
        turn = buffer.add(
            "umo:a",
            "remember this",
            "u1",
            "s1",
            "2026-10-22T12:00:00",
            source=source,
            turn_id="turn1",
        )
        self.assertIsNotNone(turn)
        rebuilt = Buffer(os.path.join(self.temp.name, "pending.json"), db=self.db)
        self.assertEqual([(item.text, item.source_id) for item in rebuilt.items],
                         [("remember this", "s1")])
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "pending.json")))

    def test_host_style_turns_without_source_id_stay_queued_separately(self) -> None:
        buffer = Buffer(db=self.db)
        buffer.add("umo:a", "Travel itinerary", "alice")
        buffer.add("umo:a", "Database index", "alice")
        self.assertEqual(
            [turn.text for turn in buffer.items], ["Travel itinerary", "Database index"]
        )
        self.assertEqual(len({turn.source_id for turn in buffer.items}), 2)
        self.assertEqual(len(self.db.pending_extractions()), 2)

    def test_success_advances_projection_and_keeps_source_rows(self) -> None:
        buffer = Buffer(db=self.db)
        buffer.add("umo:a", "Travel itinerary", "alice")
        buffer.add("umo:b", "Database index", "bob")
        self.assertEqual(buffer.mark_succeeded(list(buffer.items)), 2)
        self.assertEqual(buffer.items, [])
        self.assertEqual(Buffer(db=self.db).items, [])
        self.assertEqual(self.db.capacity_usage()["source_rows"], 2)

    def test_failed_turn_stays_retryable_with_source_text(self) -> None:
        buffer = Buffer(db=self.db)
        turn = buffer.add("umo:a", "Travel itinerary", "alice")
        self.assertEqual(buffer.mark_failed([turn], "TimeoutError"), 1)
        rows = self.db.pending_extractions()
        self.assertEqual(
            [(row["text"], row["attempts"], row["state"]) for row in rows],
            [("Travel itinerary", 1, "retrying")],
        )
        self.assertEqual(buffer.items, [turn])

    def test_failures_back_off_then_reach_terminal_state(self) -> None:
        buffer = Buffer(db=self.db)
        turn = buffer.add("umo:a", "Travel itinerary", "alice")
        self.assertEqual(buffer.mark_failed([turn], "TimeoutError", max_attempts=3), 1)
        row = self.db.pending_extractions()[0]
        self.assertEqual(row["state"], "retrying")
        self.assertEqual(row["attempts"], 1)
        self.assertGreater(row["next_attempt_at"], row["created_at"])
        self.assertEqual(self.db.ready_extraction_ids(row["created_at"]), set())
        self.assertEqual(len(self.db.pending_extractions(row["next_attempt_at"])), 1)
        buffer.mark_failed([turn], "TimeoutError", max_attempts=3)
        buffer.mark_failed([turn], "TimeoutError", max_attempts=3)
        self.assertEqual(self.db.queue_counts()["dead"], 1)
        self.assertEqual(self.db.pending_extractions(), [])
        self.assertEqual(self.db.capacity_usage()["dead_rows"], 1)

    def test_deferred_admission_parks_rows_until_release(self) -> None:
        buffer = Buffer(db=self.db)
        turn = buffer.add("umo:a", "Travel itinerary", "alice", deferred=True)
        self.assertIsNotNone(turn)
        self.assertEqual(buffer.items, [])
        self.assertEqual(self.db.queue_counts()["deferred"], 1)
        self.assertEqual(self.db.capacity_usage()["pending_rows"], 0)
        self.assertEqual(buffer.reload(), 0)
        self.assertEqual(self.db.release_deferred(10), 1)
        self.assertEqual(buffer.reload(), 1)
        self.assertEqual([row.text for row in buffer.items], ["Travel itinerary"])

    def test_projection_has_no_two_hundred_row_truncation(self) -> None:
        buffer = Buffer(db=self.db)
        for index in range(205):
            source_id = f"s{index}"
            source = Source(
                source_id,
                f"turn{index}",
                "umo:a",
                "u1",
                "user",
                f"message {index}",
                f"2026-10-22T12:{index // 60:02d}:{index % 60:02d}",
            )
            buffer.add(
                "umo:a",
                source.text,
                "u1",
                source_id,
                source.at,
                source=source,
                turn_id=source.turn_id,
            )
        rebuilt = Buffer(db=self.db)
        self.assertEqual(len(rebuilt.items), 205)

    def test_legacy_pending_file_migrates_without_changing_source_truth(self) -> None:
        path = os.path.join(self.temp.name, "pending.json")
        legacy = Buffer(path)
        legacy.add("umo:a", "legacy plan", "u1", at="2026-10-22T12:00:00")
        buffer = Buffer(path, db=self.db)
        self.assertEqual(buffer.migrate_legacy(), 1)
        self.assertTrue(os.path.exists(path + ".migrated"))
        self.assertEqual([item.text for item in buffer.items], ["legacy plan"])
        rows = self.db.pending_extractions()
        self.assertEqual([row["text"] for row in rows], ["legacy plan"])

    def test_success_closes_projection_and_failure_stays_retryable(self) -> None:
        buffer = Buffer(db=self.db)
        source = Source("s1", "t1", "umo:a", "u1", "user", "plan", "2026-10-22T12:00:00")
        turn = buffer.add(
            "umo:a",
            "plan",
            "u1",
            "s1",
            "2026-10-22T12:00:00",
            source=source,
            turn_id="t1",
        )
        self.assertIsNotNone(turn)
        self.assertEqual(buffer.mark_failed([turn], "TimeoutError"), 1)
        self.assertEqual(self.db.pending_extractions()[0]["attempts"], 1)
        self.assertEqual(buffer.mark_succeeded([turn]), 1)
        self.assertEqual(self.db.pending_extractions(), [])

    def test_capacity_usage_uses_source_state_and_active_artifacts(self) -> None:
        source = Source("s1", "t1", "umo:a", "u1", "user", "计划", "2026-10-22T12:00:00")
        self.db.enqueue_extraction(source, "topic")
        art = make("memory", {"text": "active", "level": "fact"})
        self.db.commit(art, expected_revision=0, op="create")
        usage = self.db.capacity_usage("2026-10-22T13:00:00")
        self.assertEqual(usage["source_rows"], 1)
        self.assertEqual(usage["source_bytes"], 6)
        self.assertEqual(usage["pending_rows"], 1)
        self.assertEqual(usage["pending_oldest_age_seconds"], 3600)
        self.assertEqual(usage["artifact_count"], 1)


class TraceTrimTest(unittest.TestCase):
    def test_trim_keeps_newest_rows(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        journal = Journal(Path(temp.name) / "lifecycle.jsonl")
        for index in range(8):
            journal.record("test", "info", str(index))
        self.assertEqual(journal.trim(3), 5)
        self.assertEqual([row["message"] for row in journal.events], ["5", "6", "7"])
        self.assertEqual(len(journal.path.read_text(encoding="utf-8").splitlines()), 3)


if __name__ == "__main__":
    unittest.main()
