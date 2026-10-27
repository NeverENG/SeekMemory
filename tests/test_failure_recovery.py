"""Failure recovery regressions: malformed output, partial commit and legacy buffer."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from core.artifact import make  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from tests.absorb_support import absorb  # noqa: E402
from app.flush_policy import chunk_turns  # noqa: E402
from perceive.buffer import Buffer  # noqa: E402
from perceive.extract import ExtractionParseError, parse_response, parse_response_checked  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


class FakeProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        class Resp:
            completion_text = self.text

        return Resp()


def _db():
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_recovery_"), "t.db")
    db = open_store(path)
    return db, Cache(db.artifacts), Graph(db.artifacts)


def _turn(text: str = "hello") -> DialogueTurn:
    return DialogueTurn("umo:a", "10001", "user", text, "2026-10-22T12:00:00", "s1")


class ParseRecoveryTest(unittest.TestCase):
    def test_bad_json_is_not_a_valid_empty_result(self) -> None:
        with self.assertRaises(ExtractionParseError):
            parse_response_checked("not json at all")
        self.assertEqual(parse_response("not json at all"), [])

    def test_empty_array_is_a_valid_empty_result(self) -> None:
        self.assertEqual(parse_response_checked("[]"), [])


class AbsorbRecoveryTest(unittest.TestCase):
    def test_bad_json_is_retryable(self) -> None:
        db, cache, graph = _db()
        outcome = asyncio.run(absorb(
            [_turn()], db.artifacts, db.sources, cache, graph, FakeProvider("not json at all"),
        ))
        self.assertTrue(outcome.model_failed)
        self.assertTrue(outcome.retryable)
        self.assertEqual(outcome.written, 0)

    def test_valid_empty_array_is_a_completed_empty_batch(self) -> None:
        db, cache, graph = _db()
        outcome = asyncio.run(absorb(
            [_turn()], db.artifacts, db.sources, cache, graph, FakeProvider("[]"),
        ))
        self.assertFalse(outcome.model_failed)
        self.assertFalse(outcome.retryable)
        self.assertEqual(outcome.written, 0)
        self.assertEqual(outcome.skipped, 1)

    def test_partial_commit_is_retryable(self) -> None:
        db, cache, graph = _db()
        original = db.artifacts.commit
        calls = {"count": 0}

        def flaky_commit(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("second commit failed")
            return original(*args, **kwargs)

        db.artifacts.commit = flaky_commit
        raw = json.dumps([
            {"level": "fact", "text": "first fact"},
            {"level": "fact", "text": "second fact"},
        ])
        outcome = asyncio.run(absorb(
            [_turn()], db.artifacts, db.sources, cache, graph, FakeProvider(raw),
        ))
        self.assertEqual(outcome.written, 1)
        self.assertTrue(outcome.retryable)
        self.assertTrue(outcome.errors)

    def test_impression_failure_is_reported_without_losing_incoming_memory(self) -> None:
        db, cache, graph = _db()
        self.addCleanup(db.close)
        old = make(
            "memory", {"text": "he is stubborn and helpful", "level": "impression"},
            scope="private", subject_id="10001",
        )
        db.artifacts.commit(old, expected_revision=0, op="create")
        cache.put(old)
        text = "he is stubborn but helps when it really matters"
        source = Source("s1", "t1", "umo:a", "10001", "user", text, "2026-10-22")
        db.sources.append_sources([source])
        db.conn.execute("""
            CREATE TEMP TRIGGER fail_retirement BEFORE INSERT ON artifact_versions
            WHEN NEW.revision = 2 AND
                 (SELECT state FROM nodes WHERE id = NEW.entity) = 'merged'
            BEGIN SELECT RAISE(ABORT, 'retirement failed'); END
        """)
        outcome = asyncio.run(absorb(
            [_turn(text)], db.artifacts, db.sources, cache, graph,
            FakeProvider(json.dumps([{"level": "impression", "text": text}])),
        ))
        self.assertEqual(outcome.written, 1)
        self.assertTrue(any(error.startswith("impression:") for error in outcome.errors))
        self.assertEqual(db.artifacts.get(old.header.id), old)
        incoming = db.artifacts.get(outcome.ids[0])
        self.assertEqual((incoming.header.revision, incoming.header.state), (1, "active"))
        self.assertEqual(cache.size(), 2)
        self.assertEqual(db.sources.sources_by_ids(["s1"]), {"s1": source})
        self.assertEqual(len(db.ledger.entries()), 2)


class BufferRecoveryTest(unittest.TestCase):
    def test_legacy_buffer_keeps_more_than_200_rows(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_legacy_"), "pending.json")
        buf = Buffer(path)
        for index in range(250):
            buf.add("umo:a", f"message {index}")
        self.assertEqual(len(buf.items), 250)
        self.assertEqual(len(Buffer(path).items), 250)



class OversizedTopicTest(unittest.TestCase):
    def test_chunk_turns_preserves_the_tail(self) -> None:
        turns = [_turn(f"message {index}") for index in range(250)]
        chunks = chunk_turns(turns)
        self.assertEqual([len(chunk) for chunk in chunks], [120, 120, 10])
        self.assertEqual([turn for chunk in chunks for turn in chunk], turns)


class PendingFileRecoveryTest(unittest.TestCase):
    def test_corrupt_pending_file_is_quarantined(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_pending_"), "pending.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        buf = Buffer(path)
        self.assertTrue(buf.load_error)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(path + ".corrupt"))

    def test_save_failure_is_visible(self) -> None:
        parent = os.path.join(tempfile.mkdtemp(prefix="seekmem_save_"), "not-a-dir")
        with open(parent, "w", encoding="utf-8") as handle:
            handle.write("x")
        buf = Buffer(os.path.join(parent, "pending.json"))
        buf.add("umo:a", "hello")
        self.assertTrue(buf.save_error)

class ChunkPairingTest(unittest.TestCase):
    def test_chunk_turns_keeps_a_reply_pair_on_one_side(self) -> None:
        filler = [_turn(f"message {index}") for index in range(119)]
        parent = DialogueTurn("umo:a", "10001", "user", "boundary question",
                              "2026-10-22T12:00:00", "s_u", "", "t1")
        reply = DialogueTurn("umo:a", "bot", "assistant", "boundary answer",
                             "2026-10-22T12:00:10", "s_a", "", "t1", "s_u")
        turns = filler + [parent, reply]
        chunks = chunk_turns(turns, 120)
        self.assertEqual([turn for chunk in chunks for turn in chunk], turns)
        holders = [
            chunk for chunk in chunks
            if any(turn.source_id == "s_a" for turn in chunk)
        ]
        self.assertEqual(len(holders), 1)
        self.assertTrue(any(turn.source_id == "s_u" for turn in holders[0]))

    def test_chunk_turns_with_limit_one_keeps_every_turn(self) -> None:
        turns = [_turn(f"message {index}") for index in range(5)]
        chunks = chunk_turns(turns, 1)
        self.assertEqual([len(chunk) for chunk in chunks], [1, 1, 1, 1, 1])
        self.assertEqual([turn for chunk in chunks for turn in chunk], turns)


if __name__ == "__main__":
    unittest.main()
