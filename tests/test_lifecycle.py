"""Capacity-driven Artifact lifecycle tests."""

from __future__ import annotations

import datetime
import os
import sys
import tempfile
import unittest
from contextlib import closing

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import make  # noqa: E402
from core.source import Source  # noqa: E402
from maintain.lifecycle import forget_expired  # noqa: E402
from recall.temporal import valid_at  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


class LifecycleTest(unittest.TestCase):
    def test_deadlines_agree_with_recall_and_capacity_metrics(self) -> None:
        cases = [
            ({"valid_to": "2026-10-29", "expires": "2026-11-30"}, True),
            ({"valid_to": "2026-11-30", "expires": "2026-10-29"}, True),
            ({"valid_to": "2026-10-29"}, True),
            ({"expires": "2026-10-29"}, True),
            ({"valid_to": "2026-10-29", "expires": "2026-10-30"}, True),
            ({"valid_to": "2026-10-31", "expires": "2026-11-30"}, False),
            ({"valid_to": "2026-11-30", "expires": "2026-10-31"}, False),
            ({}, False),
        ]
        for span, expired in cases:
            with self.subTest(span=span), closing(open_store(":memory:")) as db:
                cache = Cache(db.artifacts)
                art = make("memory", {"text": "dated memory", "level": "fact"}, time=span)
                db.artifacts.commit(art, expected_revision=0, op="create")
                cache.put(art)
                self.assertEqual(valid_at(art, datetime.date(2026, 10, 31)), not expired)
                usage = db.metrics.capacity_usage("2026-10-31T12:00:00")
                self.assertEqual(usage["expired_artifacts"], int(expired))
                self.assertEqual(forget_expired(db.artifacts, cache, "2026-10-31"), int(expired))
                self.assertEqual(db.artifacts.get(art.header.id).header.state,
                                 "forgotten" if expired else "active")

    def test_expired_artifact_is_forgotten_but_source_row_remains(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = open_store(os.path.join(temp.name, "memory.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = make(
            "memory",
            {"text": "old address", "level": "fact"},
            time={"expires": "2026-01-01"},
            lineage={"sources": ("s1",)},
        )
        db.sources.append_sources(
            [Source("s1", "t1", "umo:a", "u1", "user", "old address", "2025-12-01")]
        )
        db.artifacts.upsert(art)
        cache.put(art)
        self.assertEqual(forget_expired(db.artifacts, cache, "2026-10-22"), 1)
        self.assertEqual(db.artifacts.get(art.header.id).header.state, "forgotten")
        self.assertIsNone(cache.get(art.header.id))
        self.assertEqual(db.sources.source_umo("s1"), "umo:a")


    def test_forget_expired_rolls_back_on_write_failure(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = open_store(os.path.join(temp.name, "memory.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = make(
            "memory", {"text": "old address", "level": "fact"},
            time={"expires": "2026-01-01"},
        )
        db.artifacts.upsert(art)
        cache.put(art)
        original = db.artifacts._commit_conn

        def fail(*args, **kwargs):
            raise RuntimeError("write failed")

        db.artifacts._commit_conn = fail
        with self.assertRaises(RuntimeError):
            forget_expired(db.artifacts, cache, "2026-10-22")
        self.assertIs(cache.get(art.header.id), art)
        self.assertEqual(db.artifacts.get(art.header.id).header.state, "active")


if __name__ == "__main__":
    unittest.main()
