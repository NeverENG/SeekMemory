"""Verify shared repair deduplication, generations and checkpoint accounting.

验证共享补偿去重、代次及检查点计数。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cache_repair import CacheRepairs
from app.checkpoint import CheckpointManager
from core.artifact import make, revise
from store import open_store
from store.cache import Cache


class SharedCacheRepairTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.art = make("memory", {"text": "共享补偿", "level": "fact"})
        self.db.artifacts.commit(self.art, expected_revision=0, op="create")
        self.cache.put(self.art)
        self.repairs = CacheRepairs(self.db.artifacts, self.cache)

    def test_same_id_marks_deduplicate_but_keep_owner_accounting(self):
        first, second = object(), object()
        self.repairs.mark(self.art.header.id, first)
        self.repairs.mark(self.art.header.id, second)
        self.assertEqual(self.repairs.ids(), {self.art.header.id})
        self.assertEqual(self.repairs.ids(first), {self.art.header.id})
        checkpoint = CheckpointManager(self.db.artifacts, self.cache, cache_repairs=self.repairs)
        self.assertEqual(checkpoint.pending(), 0)
        self.assertEqual(self.repairs.retry(), 1)
        self.assertFalse(self.repairs.ids(second))

    def test_new_mark_during_repair_survives_and_next_attempt_reads_latest_head(self):
        entity = self.art.header.id
        self.repairs.mark(entity)
        original = self.cache.put
        newer = revise(self.art, payload={"text": "补偿中出现的新版本", "level": "fact"})

        def put(art):
            original(art)
            self.db.artifacts.commit(newer, expected_revision=1, op="revise")
            self.repairs.mark(entity)
            self.assertFalse(self.repairs.repair(entity))

        with patch.object(self.cache, "put", side_effect=put):
            self.assertFalse(self.repairs.repair(entity))
        self.assertEqual(self.repairs.ids(), {entity})
        self.assertEqual(self.repairs.retry(), 1)
        self.assertEqual(self.cache.get(entity), newer)
        self.assertFalse(self.repairs.ids())

    def test_failed_repair_retains_id_without_revising_memory(self):
        self.repairs.mark(self.art.header.id)
        with patch.object(self.cache, "put", side_effect=OSError("cache unavailable")):
            self.assertEqual(self.repairs.retry(), 0)
            self.assertEqual(self.repairs.retry(), 0)
        self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)
        self.assertEqual(len(self.db.ledger.entries()), 1)
        self.assertEqual(self.repairs.retry(), 1)


if __name__ == "__main__":
    unittest.main()
