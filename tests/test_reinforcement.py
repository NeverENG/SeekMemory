"""Reinforcement truth: final assembled IDs and cooldown accounting."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.checkpoint import CheckpointManager  # noqa: E402
from core.artifact import Strength, make, revise  # noqa: E402
from dataclasses import replace
from unittest.mock import patch
from recall.assemble import build_with_meta  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


def _fact(text: str):
    return make("memory", {"text": text, "level": "fact"},
                strength=Strength(weight=1.0))


class AssemblyTruthTest(unittest.TestCase):
    def test_budget_trimming_returns_only_final_ids(self) -> None:
        first = _fact("first fact")
        second = _fact("second fact")
        text, final_ids, dropped_ids = build_with_meta(
            [first, second], budget=14,
        )
        self.assertTrue(text)
        self.assertIn(first.header.id, final_ids)
        self.assertNotIn(second.header.id, final_ids)
        self.assertIn(second.header.id, dropped_ids)

    def test_dedupe_returns_only_final_ids(self) -> None:
        first = _fact("same fact")
        second = _fact("same fact")
        _, final_ids, dropped_ids = build_with_meta([first, second], budget=100)
        self.assertEqual(final_ids, (first.header.id,))
        self.assertIn(second.header.id, dropped_ids)


class CheckpointCooldownTest(unittest.TestCase):
    def test_same_artifact_counts_once_within_cooldown(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_reinforce_"), "t.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = _fact("cooldown fact")
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        manager = CheckpointManager(db.artifacts, cache, cooldown_seconds=3600)
        self.assertTrue(manager.record(art))
        self.assertFalse(manager.record(art))
        self.assertEqual(manager.pending(), 1)
        self.assertEqual(manager.flush(), 1)
        latest = cache.get(art.header.id)
        self.assertEqual(latest.header.strength.hits, 1)

    def test_zero_cooldown_keeps_legacy_behavior(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_reinforce_"), "t.db"))
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = _fact("legacy fact")
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        manager = CheckpointManager(db.artifacts, cache, cooldown_seconds=0)
        self.assertTrue(manager.record(art))
        self.assertTrue(manager.record(art))
        self.assertEqual(manager.flush(), 1)
        self.assertEqual(cache.get(art.header.id).header.strength.hits, 2)


class CheckpointRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.art = _fact("recoverable fact")
        self.db.artifacts.commit(self.art, expected_revision=0, op="create")
        self.cache = Cache(self.db.artifacts)
        self.cache.put(self.art)
        self.manager = CheckpointManager(self.db.artifacts, self.cache, cooldown_seconds=0)
        self.manager.record(self.art)

    def test_failed_commit_keeps_hits_and_cache(self):
        with patch.object(self.db.artifacts, "commit", side_effect=OSError):
            self.assertEqual(self.manager.flush(), 0)
        self.assertEqual(self.cache.get(self.art.header.id), self.art)
        self.assertEqual(self.manager.pending(), 1)
        self.assertEqual(self.manager.flush(), 1)
        self.assertEqual(self.cache.get(self.art.header.id).header.strength.hits, 1)

    def test_repeated_cache_failure_never_recommits_hits(self):
        with patch.object(self.cache, "put", side_effect=OSError):
            self.assertEqual(self.manager.flush(), 1)
            self.assertEqual(self.manager.flush(), 0)
            self.assertEqual(self.manager.pending(), 1)
        latest = self.db.artifacts.get(self.art.header.id)
        self.assertEqual(latest.header.strength.hits, 1)
        self.assertEqual(latest.header.revision, self.art.header.revision + 1)
        self.assertEqual(self.manager.flush(), 0)
        self.assertEqual(self.manager.pending(), 0)
        self.assertEqual(self.cache.get(self.art.header.id), latest)

    def test_repair_uses_latest_head_and_preserves_new_hits(self):
        with patch.object(self.cache, "put", side_effect=OSError):
            self.assertEqual(self.manager.flush(), 1)
            self.manager.record(self.art)
            self.assertEqual(self.manager.pending(), 1)
        head = self.db.artifacts.get(self.art.header.id)
        changed = revise(head, strength=replace(head.header.strength, weight=2.0))
        self.db.artifacts.commit(changed, expected_revision=head.header.revision, op="revise")
        self.assertEqual(self.manager.flush(), 1)
        latest = self.cache.get(self.art.header.id)
        self.assertEqual(latest.header.strength.hits, 2)
        self.assertAlmostEqual(latest.header.strength.weight, 2.1)
        self.assertEqual(latest, self.db.artifacts.get(self.art.header.id))

    def test_cache_miss_does_not_discard_stored_hits(self):
        self.cache.remove(self.art.header.id)
        self.assertEqual(self.manager.flush(), 1)
        self.assertEqual(self.cache.get(self.art.header.id).header.strength.hits, 1)

    def test_hit_arriving_during_commit_is_retained(self):
        original = self.db.artifacts.commit
        def commit(*args, **kwargs):
            original(*args, **kwargs)
            self.manager.record(self.art)
        with patch.object(self.db.artifacts, "commit", side_effect=commit):
            self.assertEqual(self.manager.flush(), 1)
        self.assertEqual(self.manager.pending(), 1)
        self.assertEqual(self.manager.flush(), 1)
        self.assertEqual(self.cache.get(self.art.header.id).header.strength.hits, 2)


if __name__ == "__main__":
    unittest.main()
