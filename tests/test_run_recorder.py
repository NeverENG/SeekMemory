"""RunRecorder owns the single write-back path for runtime runs."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    RepoEpisodeStore,
    EpisodeRecorder,
    RunRecorder,
    EpisodeRecord,
)
from store import open_store  # noqa: E402


class FakeDB:
    def __init__(self):
        self.sources = []

    def append_sources(self, sources):
        self.sources.extend(sources)
        return len(sources)


class FakeBuffer:
    def __init__(self):
        self.rows = []

    def add(self, umo, text, sender="", source_id="", at="", **kwargs):
        self.rows.append((umo, text, sender, source_id, at, kwargs))


class FakeCheckpoint:
    def __init__(self):
        self.records = []

    def record(self, art, at=""):
        self.records.append((art, at))
        return True


class FakeEpisodes:
    def __init__(self):
        self.rows = []

    def record(self, episode):
        self.rows.append(episode)


class FakeCache:
    def __init__(self, items):
        self.items = items

    def get(self, art_id):
        return self.items.get(art_id)


class RunRecorderTest(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.buffer = FakeBuffer()
        self.checkpoint = FakeCheckpoint()
        self.episodes = FakeEpisodes()
        memory = SimpleNamespace(header=SimpleNamespace(family="memory"))
        self.recorder = RunRecorder(
            sources=self.db,
            buffer=self.buffer,
            checkpoint=self.checkpoint,
            episodes=self.episodes,
            cache=FakeCache({"n1": memory}),
            clock=lambda: "2026-01-01T00:00:00",
        )

    def test_reply_write_back_is_idempotent_by_run_id(self):
        first = self.recorder.record_reply(
            run_id="run-1",
            session_id="s1",
            text="reply",
            speaker_id="bot",
            turn_id="turn-1",
            reply_to="user-1",
            recall_ids=("n1",),
        )
        second = self.recorder.record_reply(
            run_id="run-1",
            session_id="s1",
            text="reply",
            speaker_id="bot",
            turn_id="turn-1",
            reply_to="user-1",
            recall_ids=("n1",),
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)
        self.assertEqual(len(self.checkpoint.records), 1)
        self.assertEqual(first.run_id, "run-1")

    def test_projection_failure_retries_without_reappending_source(self):
        with patch.object(self.buffer, "add", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                self.recorder.record_reply(run_id="partial", session_id="s1", text="reply",
                                           speaker_id="bot", turn_id="t1")
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(self.recorder.retry_pending(), 1)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)

    def test_partial_reinforcement_never_repeats_completed_ids(self):
        self.recorder.cache.items["n2"] = self.recorder.cache.items["n1"]
        def record(art, at=""):
            if len(self.checkpoint.records) == 1:
                raise OSError("busy")
            self.checkpoint.records.append((art, at))
        with patch.object(self.checkpoint, "record", side_effect=record):
            with self.assertRaises(OSError):
                self.recorder.record_reply(run_id="partial", session_id="s1", text="reply",
                                           speaker_id="bot", recall_ids=("n1", "n2"))
        self.recorder.retry_pending()
        self.assertEqual(len(self.checkpoint.records), 2)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)

    def test_user_projection_failure_retains_original_source_identity(self):
        with patch.object(self.buffer, "add", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                self.recorder.record_user(session_id="s1", text="hello", speaker_id="u1", event_id="e1")
        source = self.db.sources[0]
        self.recorder.retry_pending()
        again = self.recorder.record_user(session_id="s1", text="hello", speaker_id="u1", event_id="e1")
        self.assertEqual(again.source_id, source.id)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)


    def test_user_turn_write_back_is_idempotent_by_event_id(self):
        first = self.recorder.record_user(
            session_id="s1",
            text="hello",
            speaker_id="u1",
            event_id="event-1",
            at="2026-01-01T00:00:00",
            deferred=True,
        )
        second = self.recorder.record_user(
            session_id="s1",
            text="hello",
            speaker_id="u1",
            event_id="event-1",
            at="2026-01-01T00:00:00",
            deferred=True,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)
        source = self.db.sources[0]
        self.assertEqual(source.session_id, "s1")
        self.assertEqual(source.speaker_id, "u1")
        self.assertEqual(source.role, "user")
        self.assertEqual(source.text, "hello")
        self.assertEqual(source.turn_id, "event-1")
        buffer_row = self.buffer.rows[0]
        self.assertEqual(buffer_row[:4], ("s1", "hello", "u1", source.id))
        self.assertIs(buffer_row[5]["source"], source)
        self.assertEqual(buffer_row[5]["turn_id"], "event-1")
        self.assertTrue(buffer_row[5]["deferred"])
        self.assertEqual(first.turn_id, "event-1")

    def test_delivery_episode_is_idempotent_and_correlated(self):
        self.recorder.record_delivery(
            run_id="run-1",
            session_id="s1",
            decision="reply",
            reason="direct_attention",
            response_chars=5,
            tool_calls=("memory_search",),
            user_source_id="u1",
            assistant_source_id="a1",
        )
        self.recorder.record_delivery(
            run_id="run-1",
            session_id="s1",
            decision="reply",
            reason="direct_attention",
            response_chars=5,
            user_source_id="u1",
            assistant_source_id="a1",
        )
        self.assertEqual(len(self.episodes.rows), 1)
        row = self.episodes.rows[0]
        self.assertEqual(row.run_id, "run-1")
        self.assertTrue(row.delivered)
        self.assertEqual(row.tool_calls, ("memory_search",))

    def test_deferred_success_writes_source_and_episode_once(self):
        first = self.recorder.record_deferred_reply(
            run_id="run-deferred",
            session_id="s1",
            text="deferred reply",
            speaker_id="bot",
            user_source_id="u1",
            at="2026-01-01T00:00:01",
        )
        second = self.recorder.record_deferred_reply(
            run_id="run-deferred",
            session_id="s1",
            text="deferred reply",
            speaker_id="bot",
            user_source_id="u1",
            at="2026-01-01T00:00:01",
        )
        self.assertEqual(first, second)
        self.assertEqual(len(self.db.sources), 1)
        self.assertEqual(len(self.buffer.rows), 1)
        self.assertEqual(len(self.episodes.rows), 1)
        self.assertEqual(self.episodes.rows[0].assistant_source_id,
                         first.assistant_source_id)
        self.assertEqual(self.episodes.rows[0].run_id, "run-deferred")

    def test_deferred_error_records_safe_episode_without_assistant_source(self):
        self.recorder.record_deferred_error(
            run_id="run-error",
            session_id="s1",
            user_source_id="u1",
            error=RuntimeError("secret message"),
        )
        self.assertEqual(self.db.sources, [])
        self.assertEqual(len(self.episodes.rows), 1)
        row = self.episodes.rows[0]
        self.assertFalse(row.delivered)
        self.assertEqual(row.error, "RuntimeError")
        self.assertEqual(row.assistant_source_id, "")
        self.assertEqual(row.run_id, "run-error")

    def test_old_runtime_episode_table_migrates_run_id(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_old_"), "memory.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE runtime_episodes ("
            "id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL, "
            "decision TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', "
            "action TEXT NOT NULL DEFAULT '', delivered INTEGER NOT NULL DEFAULT 0, "
            "response_chars INTEGER NOT NULL DEFAULT 0, "
            "tool_calls TEXT NOT NULL DEFAULT '[]', outcome TEXT NOT NULL DEFAULT '', "
            "error TEXT NOT NULL DEFAULT '', user_source_id TEXT NOT NULL DEFAULT '', "
            "assistant_source_id TEXT NOT NULL DEFAULT '')"
        )
        conn.commit()
        conn.close()
        db = open_store(path)
        self.addCleanup(db.close)
        db.runtime_episodes.append({
            "id": "ep-old", "at": "2026-01-01T00:00:00", "session_id": "s1",
            "run_id": "run-old",
        })
        self.assertEqual(db.runtime_episodes.list("s1")[0]["run_id"], "run-old")

    def test_database_rejects_duplicate_episode_run_ids(self):
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_recorder_"), "memory.db"))
        self.addCleanup(db.close)
        sink = RepoEpisodeStore(db.runtime_episodes)
        recorder = EpisodeRecorder(sink)
        episode = EpisodeRecord(
            session_id="s1", at="2026-01-01T00:00:00", decision="reply",
            reason="direct", action="reply", delivered=True, outcome="ok",
            run_id="run-1",
        )
        recorder.record(episode)
        recorder.record(episode)
        self.assertEqual(sink.last_error, "")
        rows = db.runtime_episodes.list("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
