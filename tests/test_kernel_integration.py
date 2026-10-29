"""Exercise atomic storage, checkpoint and migration behavior.

验证原子存储、检查点及迁移行为。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sqlite3
import tempfile
from app.checkpoint import CheckpointManager
from core.artifact import revise
from core.source import Source
from core.versioning import StateEvent, VersionError
from store import open_store
from store.cache import Cache
from store.ledger import Ledger
from kernel_support import _memory

class CommitTest(unittest.TestCase):
    def test_cas_history_and_ledger(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        first = _memory(subject="owner")
        db.artifacts.commit(first, expected_revision=0, op="create", reason="test",
                  source_ids=("source-1",))
        self.assertEqual(db.artifacts.get(first.header.id).header.subject_id, "owner")
        second = revise(first, payload={"text": "updated", "level": "fact"})
        db.artifacts.commit(second, expected_revision=1, op="revise", reason="update")
        rows = db.artifacts.history(first.header.id)
        self.assertEqual([r["revision"] for r in rows], [1, 2])
        self.assertEqual([r["op"] for r in rows], ["create", "revise"])
        self.assertEqual(len(db.ledger.entries()), 2)
        self.assertTrue(Ledger(db.ledger).verify())
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM artifact_evidence").fetchone()[0], 1)
        with self.assertRaises(VersionError):
            db.artifacts.commit(revise(second, payload={"text": "stale", "level": "fact"}), expected_revision=1, op="revise")
        bad_event = StateEvent("bad", first.header.id, 2, "reinforce", {}, "t")
        with self.assertRaises(VersionError):
            db.artifacts.commit(second, expected_revision=99, op="reinforce", state_events=(bad_event,))
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM state_events WHERE id = 'bad'").fetchone()[0], 0)
        event = StateEvent("e1", first.header.id, 2, "reinforce", {"hits": 1}, "t")
        reinforced = revise(second, payload={"text": "updated", "level": "fact"})
        db.artifacts.commit(
            reinforced,
            expected_revision=2,
            op="reinforce",
            state_events=(event,),
        )
        self.assertEqual(
            db.conn.execute("SELECT COUNT(*) FROM state_events").fetchone()[0], 1
        )


class StoreBoundaryTest(unittest.TestCase):
    def test_source_batch_and_subject_index(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        src = Source("s1", "turn1", "umo1", "u1", "user", "hello", "t")
        self.assertEqual(db.sources.append_sources([src]), 1)
        self.assertEqual(db.sources.append_sources([src]), 0)
        self.assertEqual(db.sources.source_umo("s1"), "umo1")
        art = _memory(subject="u1")
        cache = Cache(db.artifacts)
        cache.put(art)
        self.assertEqual([a.header.id for a in cache.by_subject("u1")], [art.header.id])


class CheckpointTest(unittest.TestCase):
    def test_checkpoint_creates_revision_and_state_event(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        art = _memory()
        db.artifacts.commit(art, expected_revision=0, op="create")
        cache.put(art)
        mgr = CheckpointManager(db.artifacts, cache, cooldown_seconds=0)
        mgr.record(art)
        mgr.record(art)
        self.assertEqual(mgr.flush(), 1)
        got = cache.get(art.header.id)
        self.assertEqual(got.header.revision, 2)
        self.assertEqual(got.header.strength.hits, 2)
        self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM state_events").fetchone()[0], 1)


class MigrationTest(unittest.TestCase):
    def test_old_nodes_table_gets_subject_id(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = str(Path(directory.name) / "old.db")
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, family TEXT, level TEXT, parent TEXT, blob TEXT, state TEXT, scope TEXT, strength TEXT, time TEXT, said_by TEXT, shareable TEXT, created_at TEXT, updated_at TEXT, revision INTEGER, lineage TEXT)")
        con.commit()
        con.close()
        db = open_store(path)
        self.addCleanup(db.close)
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(nodes)")}
        self.assertIn("subject_id", cols)


if __name__ == "__main__":
    unittest.main()
