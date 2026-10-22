"""Capacity-driven Artifact lifecycle tests."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import make  # noqa: E402
from core.source import Source  # noqa: E402
from maintain.lifecycle import forget_expired  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


class LifecycleTest(unittest.TestCase):
    def test_expired_artifact_is_forgotten_but_source_row_remains(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db = DB(os.path.join(temp.name, "memory.db"))
        self.addCleanup(db.close)
        cache = Cache(db)
        art = make(
            "memory",
            {"text": "old address", "level": "fact"},
            time={"expires": "2026-01-01"},
            lineage={"sources": ("s1",)},
        )
        db.append_sources(
            [Source("s1", "t1", "umo:a", "u1", "user", "old address", "2025-12-01")]
        )
        db.upsert(art)
        cache.put(art)
        self.assertEqual(forget_expired(db, cache, "2026-10-22"), 1)
        self.assertEqual(db.get(art.header.id).header.state, "forgotten")
        self.assertIsNone(cache.get(art.header.id))
        self.assertEqual(db.source_umo("s1"), "umo:a")


if __name__ == "__main__":
    unittest.main()
