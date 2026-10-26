"""History import task persistence and Source queue isolation."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source import Source, SourceQueueEntry
from store import open_store
from store.imports import SourceIdentityConflict


class HistoryImportStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)

    def test_legacy_preflight_schema_migrates_reply_lookup_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            legacy = sqlite3.connect(path)
            legacy.execute(
                "CREATE TABLE history_import_preflight ("
                "stage_key TEXT NOT NULL, source_id TEXT NOT NULL, "
                "fingerprint TEXT NOT NULL, topic_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL, PRIMARY KEY(stage_key, source_id))"
            )
            legacy.close()

            migrated = open_store(str(path))
            try:
                columns = {
                    str(row[1])
                    for row in migrated.conn.execute(
                        "PRAGMA table_info(history_import_preflight)"
                    )
                }
                indexes = {
                    str(row[1])
                    for row in migrated.conn.execute(
                        "PRAGMA index_list(history_import_preflight)"
                    )
                }
            finally:
                migrated.close()

        self.assertTrue({"role", "reply_to"}.issubset(columns))
        self.assertIn("idx_history_import_preflight_reply", indexes)

    def _source(
        self,
        text: str = "history",
        *,
        source_id: str = "si_1",
        role: str = "assistant",
        reply_to: str | None = None,
    ) -> Source:
        return Source(
            source_id,
            source_id,
            "qq:FriendMessage:target",
            "bot-platform-id",
            role,
            text,
            "2026-10-01T00:00:00+00:00",
            reply_to=reply_to,
            metadata={"origin": {"format_id": "chatlab", "external_message_id": "m1"}},
        )

    def test_late_parent_user_retargets_preflighted_assistant_topic(self) -> None:
        imports = self.db.imports
        assistant = SourceQueueEntry(
            self._source(source_id="assistant-id", reply_to="user-id"),
            "assistant-topic",
        )
        parent = SourceQueueEntry(
            self._source(source_id="user-id", role="user"), "parent-topic"
        )

        imports.validate_sources("stage-one", [assistant])
        self.assertEqual(
            imports.preflight_user_topics("stage-one", ["user-id"]), {}
        )
        imports.validate_sources("stage-one", [parent])

        self.assertEqual(
            imports.preflight_user_topics("stage-one", ["user-id"]),
            {"user-id": "parent-topic"},
        )
        imports.create_task("task-one", "stage-one")
        imports.set_status("task-one", "running")
        imports.admit_sources("task-one", [assistant, parent], stage_key="stage-one")
        rows = imports.topic_sources("task-one", "parent-topic")
        self.assertEqual(
            {row["source_id"] for row in rows}, {"assistant-id", "user-id"}
        )

    def test_import_queue_is_hidden_from_live_projection_until_terminal(self) -> None:
        imports = self.db.imports
        imports.create_task("task-1", "stage-random", skipped_count=2)
        self.assertTrue(imports.set_status("task-1", "running"))
        source = self._source()
        entry = SourceQueueEntry(source, "topic-1")

        self.assertEqual(imports.validate_sources("stage-random", [entry]), {"unique": 1, "duplicates": 0, "existing": 0})
        self.assertEqual(imports.admit_sources("task-1", [entry], stage_key="stage-random"), 1)
        self.assertEqual(imports.admit_sources("task-1", [entry], stage_key="stage-random"), 0)
        self.assertEqual(self.db.extraction.pending_extractions(), [])
        self.assertEqual(imports.topic_ids("task-1"), ["topic-1"])
        self.assertEqual(imports.counts("task-1"), {"pending": 1, "extracted": 0, "failed": 0})
        self.assertEqual(imports.topic_sources("task-1", "topic-1")[0]["text"], "history")

        self.db.extraction.mark_extraction_succeeded([source.id])
        self.assertEqual(imports.counts("task-1"), {"pending": 0, "extracted": 1, "failed": 0})
        imports.finish_task("task-1", "completed", persona_status="unchanged")
        summary = imports.task("task-1")
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["extracted_count"], 1)
        self.assertEqual(summary["skipped_count"], 2)
        self.assertNotIn("stage_key", summary)
        self.assertNotIn("target", str(summary))
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM history_import_sources").fetchone()[0],
            0,
        )

    def test_conflicting_import_identity_rolls_back_entire_batch(self) -> None:
        self.db.imports.create_task("task-1", "stage-random")
        self.db.imports.set_status("task-1", "running")
        first = SourceQueueEntry(self._source(), "topic-1")
        self.db.imports.validate_sources("stage-random", [first])
        self.db.imports.admit_sources("task-1", [first], stage_key="stage-random")

        self.db.imports.create_task("task-2", "another-stage")
        self.db.imports.set_status("task-2", "running")
        with self.assertRaises(SourceIdentityConflict):
            self.db.imports.validate_sources(
                "another-stage", [SourceQueueEntry(self._source("changed"), "topic-2")]
            )
        self.assertEqual(self.db.sources.sources_by_ids(["si_1"])["si_1"].text, "history")
        self.assertEqual(self.db.imports.task("task-2")["source_count"], 0)

    def test_duplicate_existing_identity_is_counted_once_per_file_row(self) -> None:
        first = SourceQueueEntry(self._source(), "topic-1")
        self.db.imports.validate_sources("stage-one", [first])
        self.db.imports.create_task("task-1", "stage-one")
        self.db.imports.set_status("task-1", "running")
        self.db.imports.admit_sources("task-1", [first], stage_key="stage-one")

        result = self.db.imports.validate_sources("stage-two", [first, first])
        self.assertEqual(result, {"unique": 1, "duplicates": 1, "existing": 1})
        self.assertEqual(result["duplicates"] + result["existing"], 2)

    def test_running_task_is_recovered_as_interrupted_and_summary_prunes(self) -> None:
        selection = {
            "bot_platform_id": "bot-1",
            "target_platform_id": "user-1",
            "target_umo": "qq:FriendMessage:user-1",
            "bot_member_id": "bot-1",
            "target_member_id": "user-1",
        }
        self.db.imports.create_task(
            "task-1", "stage-random", selection=selection, at="2026-09-01T00:00:00"
        )
        self.db.imports.set_status("task-1", "running", at="2026-09-01T01:00:00")
        self.assertEqual(self.db.imports.recover_interrupted("2026-09-02T00:00:00"), 1)
        self.assertEqual(self.db.imports.task("task-1")["status"], "interrupted")
        self.assertTrue(self.db.imports.task("task-1")["can_retry"])
        self.assertEqual(self.db.imports.task_selection("task-1"), selection)
        self.assertNotIn("target_umo", str(self.db.imports.task("task-1")))
        self.db.imports.finish_task(
            "task-1", "failed", persona_status="not_run", retain_stage=True,
            at="2026-09-02T00:00:00",
        )
        self.assertTrue(self.db.imports.task_stage("task-1")["stage_key"])
        self.assertEqual(self.db.imports.task_selection("task-1"), selection)
        self.assertEqual(
            self.db.imports.prune(now="2026-10-03T00:00:00", retention_days=30), 1
        )
        self.assertIsNone(self.db.imports.task("task-1"))

    def test_abandon_partial_retry_clears_private_selection(self) -> None:
        selection = {"target_umo": "qq:FriendMessage:user-1"}
        self.db.imports.create_task("task-1", "stage-random", selection=selection)
        self.db.imports.finish_task(
            "task-1", "partial", persona_status="unchanged", retain_stage=True
        )
        self.assertTrue(self.db.imports.task("task-1")["can_retry"])
        self.assertTrue(self.db.imports.abandon_task("task-1"))
        task = self.db.imports.task("task-1")
        self.assertEqual(task["status"], "abandoned")
        self.assertFalse(task["can_retry"])
        self.assertEqual(self.db.imports.task_selection("task-1"), {})

    def test_schema_migrates_existing_import_tasks_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "legacy.db"
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "CREATE TABLE history_import_tasks ("
                    "id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'queued', "
                    "stage_key TEXT NOT NULL DEFAULT '', format_id TEXT NOT NULL DEFAULT 'chatlab', "
                    "source_count INTEGER NOT NULL DEFAULT 0, duplicate_count INTEGER NOT NULL DEFAULT 0, "
                    "skipped_count INTEGER NOT NULL DEFAULT 0, pending_count INTEGER NOT NULL DEFAULT 0, "
                    "extracted_count INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0, "
                    "error_types TEXT NOT NULL DEFAULT '[]', persona_status TEXT NOT NULL DEFAULT 'pending', "
                    "created_at TEXT NOT NULL, updated_at TEXT NOT NULL, terminal_at TEXT NOT NULL DEFAULT '', "
                    "stage_expires_at TEXT NOT NULL DEFAULT '')"
                )
            legacy = open_store(str(path))
            try:
                columns = {
                    str(row[1])
                    for row in legacy.conn.execute("PRAGMA table_info(history_import_tasks)")
                }
                self.assertIn("selection_json", columns)
            finally:
                legacy.close()


if __name__ == "__main__":
    unittest.main()
