"""Capacity-driven Artifact lifecycle tests."""

from __future__ import annotations

import os
import tempfile
import unittest

from core.artifact import make
from core.source import Source
from maintain.lifecycle import forget_expired
from store.cache import Cache
from store.db import DB


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
