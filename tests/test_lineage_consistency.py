"""Lineage and cache consistency regressions for impression revision."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, Strength, content_of, make, revise  # noqa: E402
from core.source import Source  # noqa: E402
from core.versioning import VersionError  # noqa: E402
from maintain.impression import revise_impression  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


def _impression(text: str, sources: tuple[str, ...] = (),
                derived_from: tuple[str, ...] = ()) -> object:
    return make(
        "memory",
        {"text": text, "level": "impression"},
        strength=Strength(weight=1.5),
        scope="private",
        subject_id="u1",
        lineage=Lineage(sources=sources, derived_from=derived_from),
    )


class ImpressionLineageTest(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory(prefix="seekmem_lineage_")
        self.addCleanup(temp.cleanup)
        self.path = os.path.join(temp.name, "t.db")
        self.db = open_store(self.path)
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.db.sources.append_sources([
            Source("s1", "t1", "umo:a", "u1", "user", "first observation", "2026-10-22"),
            Source("s2", "t2", "umo:a", "u1", "user", "second observation", "2026-10-23"),
        ])

    def _save(self, art):
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=art.header.lineage.sources
        )
        self.cache.put(art)
        return art

    def _pair(self, text):
        old = self._save(_impression("he is stubborn", ("s1",)))
        incoming = self._save(_impression(text, ("s2",)))
        return old, incoming

    def _reopen(self):
        self.db.close()
        self.db = open_store(self.path)
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.cache.load()

    def _snapshot(self, *arts):
        return {
            "heads": [self.db.artifacts.get(art.header.id) for art in arts],
            "records": [self.db.artifacts.inspect_record(art.header.id) for art in arts],
            "ledger": [dict(row) for row in self.db.ledger.entries()],
            "sources": self.db.sources.sources_by_ids(["s1", "s2"]),
        }

    def _assert_merged(self, old, incoming, result):
        self.assertEqual(result.header.id, old.header.id)
        self.assertEqual(result.header.revision, 2)
        self.assertEqual(result.header.strength.hits, old.header.strength.hits + 1)
        self.assertEqual(result.header.lineage.sources, ("s1", "s2"))
        self.assertEqual(self.db.artifacts.get(old.header.id), result)
        retired = self.db.artifacts.get(incoming.header.id)
        self.assertEqual((retired.header.revision, retired.header.state), (2, "merged"))
        self.assertEqual(self.cache.active(), [result])
        self.assertEqual(len(self.db.artifacts.history(old.header.id)), 2)
        self.assertEqual(len(self.db.artifacts.history(incoming.header.id)), 2)
        self.assertEqual(len(self.db.ledger.entries()), 4)
        self.assertTrue(self.db.ledger.verify())

    def test_reword_unions_sources_without_self_reference(self) -> None:
        old, incoming = self._pair("he is stubborn but helps when it really matters")
        got = revise_impression(self.db.artifacts, self.cache, incoming)
        self._assert_merged(old, incoming, got)
        self.assertEqual(content_of(got), "he is stubborn but helps when it really matters")
        self.assertIn(incoming.header.id, got.header.lineage.derived_from)
        self.assertNotIn(got.header.id, got.header.lineage.derived_from)

    def test_reinforce_unions_sources(self) -> None:
        old, incoming = self._pair("he is stubborn")
        got = revise_impression(self.db.artifacts, self.cache, incoming)
        self._assert_merged(old, incoming, got)
        self.assertEqual(content_of(got), content_of(old))

    def _check_failure_and_retry(self, text):
        old, incoming = self._pair(text)
        before = self._snapshot(old, incoming)
        cache_version = self.cache.version
        self.db.conn.execute("""
            CREATE TEMP TRIGGER fail_retirement BEFORE INSERT ON artifact_versions
            WHEN NEW.revision = 2 AND
                 (SELECT state FROM nodes WHERE id = NEW.entity) = 'merged'
            BEGIN SELECT RAISE(ABORT, 'retirement failed'); END
        """)
        with self.assertRaises(sqlite3.IntegrityError):
            revise_impression(self.db.artifacts, self.cache, incoming)
        self.assertEqual(self._snapshot(old, incoming), before)
        self.assertEqual(self.cache.version, cache_version)
        self.assertIs(self.cache.get(old.header.id), old)
        self.assertIs(self.cache.get(incoming.header.id), incoming)

        self._reopen()  # Reopening also removes the temporary failure trigger.
        self.assertEqual(self._snapshot(old, incoming), before)
        got = revise_impression(self.db.artifacts, self.cache, incoming)
        self._assert_merged(old, incoming, got)
        after = self._snapshot(old, incoming)
        self._reopen()
        self.assertEqual(self._snapshot(old, incoming), after)
        self.assertEqual(self.cache.active(), [got])

    def test_reinforce_failure_rolls_back_and_retry_succeeds(self) -> None:
        self._check_failure_and_retry("he is stubborn")

    def test_reword_failure_rolls_back_and_retry_succeeds(self) -> None:
        self._check_failure_and_retry("he is stubborn but helps when it really matters")

    def _check_revision_conflict(self, text):
        old, incoming = self._pair(text)
        newer = revise(incoming, payload={**incoming.payload, "text": text + " updated elsewhere"})
        self.db.artifacts.commit(
            newer, expected_revision=1, op="revise", source_ids=("s2",)
        )
        self.cache.put(newer)
        before = self._snapshot(old, incoming)
        cache_version = self.cache.version
        with self.assertRaises(VersionError):
            revise_impression(self.db.artifacts, self.cache, incoming)
        self.assertEqual(self._snapshot(old, incoming), before)
        self.assertEqual(self.cache.version, cache_version)
        self.assertIs(self.cache.get(old.header.id), old)
        self.assertIs(self.cache.get(incoming.header.id), newer)
        self._reopen()
        self.assertEqual(self._snapshot(old, incoming), before)

    def test_reinforce_conflict_preserves_both_heads(self) -> None:
        self._check_revision_conflict("he is stubborn")

    def test_reword_conflict_preserves_both_heads(self) -> None:
        self._check_revision_conflict("he is stubborn but helps when it really matters")


if __name__ == "__main__":
    unittest.main()
