"""Exercise persisted pending rows, capacity usage and trace trimming.

验证持久化待处理行、容量统计及追踪裁剪。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import os
import datetime
import logging
import tempfile
from app.contracts import DialogueTurn
from core.artifact import make
from core.source import Source
from perceive.buffer import Buffer
from store import open_store
from core.capacity import CapacityGovernor
from services.capacity_service import CapacityService
from webui.journal import Journal
from webui.trace import Trace

class ExtractionProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db = open_store(os.path.join(self.temp.name, "memory.db"))

    def tearDown(self) -> None:
        self.db.close()
        self.temp.cleanup()

    def test_pending_projection_is_rebuilt_from_source_and_state(self) -> None:
        source = Source(
            "s1", "turn1", "umo:a", "u1", "user", "remember this", "2026-10-22T12:00:00"
        )
        buffer = Buffer(os.path.join(self.temp.name, "pending.json"), extraction=self.db.extraction)
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
        rebuilt = Buffer(os.path.join(self.temp.name, "pending.json"), extraction=self.db.extraction)
        self.assertEqual([(item.text, item.source_id) for item in rebuilt.items],
                         [("remember this", "s1")])
        self.assertFalse(os.path.exists(os.path.join(self.temp.name, "pending.json")))

    def test_host_style_turns_without_source_id_stay_queued_separately(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
        buffer.add("umo:a", "Travel itinerary", "alice")
        buffer.add("umo:a", "Database index", "alice")
        self.assertEqual(
            [turn.text for turn in buffer.items], ["Travel itinerary", "Database index"]
        )
        self.assertEqual(len({turn.source_id for turn in buffer.items}), 2)
        self.assertEqual(len(self.db.extraction.pending_extractions()), 2)

    def test_success_advances_projection_and_keeps_source_rows(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
        buffer.add("umo:a", "Travel itinerary", "alice")
        buffer.add("umo:b", "Database index", "bob")
        self.assertEqual(buffer.mark_succeeded(list(buffer.items)), 2)
        self.assertEqual(buffer.items, [])
        self.assertEqual(Buffer(extraction=self.db.extraction).items, [])
        self.assertEqual(self.db.metrics.capacity_usage()["source_rows"], 2)

    def test_failed_turn_stays_retryable_with_source_text(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
        turn = buffer.add("umo:a", "Travel itinerary", "alice")
        self.assertEqual(buffer.mark_failed([turn], "TimeoutError"), 1)
        rows = self.db.extraction.pending_extractions()
        self.assertEqual(
            [(row["text"], row["attempts"], row["state"]) for row in rows],
            [("Travel itinerary", 1, "retrying")],
        )
        self.assertEqual(buffer.items, [turn])

    def test_failures_back_off_then_reach_terminal_state(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
        turn = buffer.add("umo:a", "Travel itinerary", "alice")
        self.assertEqual(buffer.mark_failed([turn], "TimeoutError", max_attempts=3), 1)
        row = self.db.extraction.pending_extractions()[0]
        self.assertEqual(row["state"], "retrying")
        self.assertEqual(row["attempts"], 1)
        self.assertGreater(row["next_attempt_at"], row["created_at"])
        self.assertEqual(self.db.extraction.ready_extraction_ids(row["created_at"]), set())
        self.assertEqual(len(self.db.extraction.pending_extractions(row["next_attempt_at"])), 1)
        buffer.mark_failed([turn], "TimeoutError", max_attempts=3)
        buffer.mark_failed([turn], "TimeoutError", max_attempts=3)
        self.assertEqual(self.db.extraction.queue_counts()["dead"], 1)
        self.assertEqual(self.db.extraction.pending_extractions(), [])
        self.assertEqual(self.db.metrics.capacity_usage()["dead_rows"], 1)

    def test_deferred_admission_parks_rows_until_release(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
        turn = buffer.add("umo:a", "Travel itinerary", "alice", deferred=True)
        self.assertIsNotNone(turn)
        self.assertEqual(buffer.items, [])
        self.assertEqual(self.db.extraction.queue_counts()["deferred"], 1)
        self.assertEqual(self.db.metrics.capacity_usage()["pending_rows"], 0)
        self.assertEqual(buffer.reload(), 0)
        self.assertEqual(self.db.extraction.release_deferred(10), 1)
        self.assertEqual(buffer.reload(), 1)
        self.assertEqual([row.text for row in buffer.items], ["Travel itinerary"])

    def test_capacity_recovers_deferred_backlog_after_restart(self) -> None:
        count = 200
        at = datetime.datetime.now().isoformat(timespec="seconds")
        for index in range(count):
            source = Source(f"s{index}", f"t{index}", "umo:a", "u1", "user", "queued message", at)
            self.db.extraction.enqueue_extraction(source, "topic", deferred=True)
        self.db.close()
        self.db = open_store(os.path.join(self.temp.name, "memory.db"))
        buffer = Buffer(extraction=self.db.extraction)
        capacity = CapacityService(
            metrics=self.db.metrics, extraction=self.db.extraction, maintenance=None,
            trace=Trace(), journal=Journal(Path(self.temp.name) / "journal.jsonl"),
            governor=CapacityGovernor(), config=lambda key, default: default,
            logger=logging.getLogger(__name__), on_release=buffer.reload,
        )
        for _ in range(count // capacity.thresholds.release_batch):
            capacity.apply_maintenance(capacity.observe())
            self.assertTrue(buffer.items)
            self.assertLessEqual(len(buffer.items), capacity.thresholds.release_batch)
            buffer.mark_succeeded(list(buffer.items))
        counts = self.db.extraction.queue_counts()
        self.assertEqual((counts["pending"], counts["deferred"], counts["extracted"]), (0, 0, count))
        self.assertEqual(self.db.metrics.capacity_usage()["source_rows"], count)

    def test_projection_has_no_two_hundred_row_truncation(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
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
        rebuilt = Buffer(extraction=self.db.extraction)
        self.assertEqual(len(rebuilt.items), 205)

    def test_legacy_pending_file_migrates_without_changing_source_truth(self) -> None:
        path = os.path.join(self.temp.name, "pending.json")
        legacy = Buffer(path)
        legacy.add("umo:a", "legacy plan", "u1", at="2026-10-22T12:00:00")
        buffer = Buffer(path, extraction=self.db.extraction)
        self.assertEqual(buffer.migrate_legacy(), 1)
        self.assertTrue(os.path.exists(path + ".migrated"))
        self.assertEqual([item.text for item in buffer.items], ["legacy plan"])
        rows = self.db.extraction.pending_extractions()
        self.assertEqual([row["text"] for row in rows], ["legacy plan"])

    def test_success_closes_projection_and_failure_stays_retryable(self) -> None:
        buffer = Buffer(extraction=self.db.extraction)
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
        self.assertEqual(self.db.extraction.pending_extractions()[0]["attempts"], 1)
        self.assertEqual(buffer.mark_succeeded([turn]), 1)
        self.assertEqual(self.db.extraction.pending_extractions(), [])

    def test_capacity_usage_uses_source_state_and_active_artifacts(self) -> None:
        source = Source("s1", "t1", "umo:a", "u1", "user", "计划", "2026-10-22T12:00:00")
        self.db.extraction.enqueue_extraction(source, "topic")
        art = make("memory", {"text": "active", "level": "fact"})
        self.db.artifacts.commit(art, expected_revision=0, op="create")
        usage = self.db.metrics.capacity_usage("2026-10-22T13:00:00")
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


class ExtractionRetryLimitTest(unittest.TestCase):
    def test_retry_limit_moves_row_to_dead(self) -> None:
        db = open_store(":memory:")
        self.addCleanup(db.close)
        source = Source("s1", "t1", "umo:a", "u1", "user", "x", "2026-10-22T12:00:00")
        db.extraction.enqueue_extraction(source, "topic")
        db.extraction.mark_extraction_failed(["s1"], "TimeoutError", max_attempts=1)
        self.assertEqual(db.extraction.queue_counts()["dead"], 1)
        self.assertEqual(db.extraction.pending_extractions(), [])


if __name__ == "__main__":
    unittest.main()
