"""Tree revisions and hierarchy changes commit or fail as one observable operation."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import make, revise
from core.source import Source
from core.versioning import VersionError

from core.domain.memory.tree_change import TreeChange, TreeLink, TreeRevision
from maintain.writer import MaintenanceWriter
from services.tree_service import TreeService
from store import open_store
from store.cache import Cache


class TreeChangeTransactionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "tree.db")
        self.db = open_store(self.path)
        self.addCleanup(self.db.close)
        self.source = Source(
            "s_tree_tx", "turn_tree_tx", "session_tree_tx", "u1", "user", "observation"
        )
        self.db.sources.append_sources([self.source])
        self.cache = Cache(self.db.artifacts)
        self.tree = TreeService(self.db.artifacts, self.cache)

    def memory(self, node_id: str, level: str = "fact"):
        return make(
            "memory",
            {"level": level, "text": node_id},
            id=node_id,
            subject_id="u1",
            lineage={"sources": (self.source.id,)},
        )

    def save(self, art):
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=(self.source.id,)
        )

    def prepared(self, operation_id="correction"):
        child = self.db.artifacts.get("child")
        left = self.db.artifacts.get("left")
        right = self.db.artifacts.get("right")
        before = self.db.artifacts.tree_snapshot("child")
        return TreeChange(
            operation_id,
            (
                TreeRevision(
                    revise(child, {"level": "fact", "text": "corrected"}),
                    1,
                    (self.source.id,),
                ),
                TreeRevision(revise(left, state="forgotten"), 1, (self.source.id,)),
                TreeRevision(revise(right, state="forgotten"), 1, (self.source.id,)),
            ),
            (("child", 1), ("left", 1), ("right", 1)),
            (("child", before),),
            (("child", ()),),
            "revise",
            "correction",
        )

    def with_two_parents(self):
        for node_id, level in (("left", "impression"), ("right", "impression")):
            self.save(self.memory(node_id, level))
        self.tree.add_under(self.memory("child"), ("left", "right"))

    def test_two_parent_correction_removes_both_edges_with_versions_and_ledger(self):
        self.with_two_parents()
        change = self.prepared()
        self.assertTrue(self.db.artifacts.commit_tree_change(change))
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), [])
        self.assertEqual(self.db.artifacts.get("child").payload["text"], "corrected")
        self.assertEqual(
            [self.db.artifacts.get(key).header.state for key in ("left", "right")],
            ["forgotten", "forgotten"],
        )
        self.assertEqual(
            [len(self.db.artifacts.history(key)) for key in ("child", "left", "right")],
            [2, 2, 2],
        )
        self.assertTrue(self.db.ledger.verify())
        logged = str(
            tuple(self.db.conn.execute("SELECT * FROM tree_change_log").fetchone())
        )
        self.assertNotIn("corrected", logged)
        self.assertNotIn(self.source.text, logged)

    def test_failure_on_second_parent_write_rolls_back_everything(self):
        self.with_two_parents()
        self.db.conn.execute(
            "CREATE TRIGGER reject_right BEFORE UPDATE ON nodes "
            "WHEN NEW.id = 'right' BEGIN SELECT RAISE(ABORT, 'reject'); END"
        )
        before = self.db.ledger.last_hash()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.artifacts.commit_tree_change(self.prepared())
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), ["left", "right"])
        self.assertEqual(
            [
                self.db.artifacts.get(key).header.revision
                for key in ("child", "left", "right")
            ],
            [1, 1, 1],
        )
        self.assertEqual(before, self.db.ledger.last_hash())
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM tree_change_log").fetchone()[0],
            1,
        )

    def test_edge_and_log_failures_rollback_and_cache_is_unchanged(self):
        parent = self.memory("parent", "impression")
        self.save(parent)
        child = self.memory("child")
        for table in ("edges", "tree_change_log"):
            with self.subTest(table=table):
                self.db.conn.execute(
                    f"CREATE TRIGGER fail_{table} BEFORE INSERT ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, 'reject'); END"
                )
                before, cache_version = self.db.ledger.last_hash(), self.cache.version
                with self.assertRaises(sqlite3.IntegrityError):
                    self.tree.add_under(child, ("parent",))
                self.assertIsNone(self.db.artifacts.get("child"))
                self.assertEqual(self.db.artifacts.tree_children("parent", 8), [])
                self.assertEqual(before, self.db.ledger.last_hash())
                self.assertEqual(cache_version, self.cache.version)
                self.db.conn.execute(f"DROP TRIGGER fail_{table}")

    def test_snapshot_conflict_and_idempotent_replay_after_reopen(self):
        self.with_two_parents()
        change = self.prepared()
        self.db.artifacts.add_edge("unplanned", "child", "tree_child:unplanned", 1.0)
        with self.assertRaises(VersionError):
            self.db.artifacts.commit_tree_change(change)
        self.assertEqual(self.db.artifacts.get("child").header.revision, 1)
        self.db.conn.execute("DELETE FROM edges WHERE src = 'unplanned'")
        self.db.conn.commit()
        self.assertTrue(self.db.artifacts.commit_tree_change(change))
        self.assertFalse(self.db.artifacts.commit_tree_change(change))
        self.db.close()
        reopened = open_store(self.path)
        self.addCleanup(reopened.close)
        self.assertFalse(reopened.artifacts.commit_tree_change(change))
        conflicting = TreeChange(
            "correction",
            change.writes,
            change.observed,
            change.edges_before,
            (("child", (TreeLink("left", "child"),)),),
            change.op,
            change.reason,
        )
        with self.assertRaises(VersionError):
            reopened.artifacts.commit_tree_change(conflicting)

    def test_reviewed_parent_can_stay_active_only_when_revised_and_kept(self):
        self.with_two_parents()
        original = self.prepared("keep-left")
        after = (("child", (TreeLink("left", "child"),)),)
        left = self.db.artifacts.get("left")
        writes = (
            original.writes[0],
            TreeRevision(
                revise(left, {"level": "impression", "text": "reviewed"}),
                1,
                (self.source.id,),
            ),
            original.writes[2],
        )
        change = TreeChange(
            original.operation_id,
            writes,
            original.observed,
            original.edges_before,
            after,
            "revise",
            "review",
        )
        cache = Cache(self.db.artifacts)
        cache.load()
        writer = MaintenanceWriter(self.db.artifacts, cache)
        self.assertEqual(writer.execute_tree(change), 3)
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), ["left"])
        self.assertEqual(cache.get("left").payload["text"], "reviewed")
        self.assertIsNone(cache.get("right"))
        self.assertEqual(writer.execute_tree(change), 0)

    def test_service_retry_does_not_append_a_second_revision(self):
        self.save(self.memory("parent", "impression"))
        child = self.memory("child")
        self.tree.add_under(child, ("parent",))
        ledger = self.db.ledger.last_hash()
        self.assertIs(self.tree.add_under(child, ("parent",)), child)
        self.assertEqual(self.db.artifacts.get("child").header.revision, 1)
        self.assertEqual(self.db.ledger.last_hash(), ledger)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM tree_change_log").fetchone()[0],
            1,
        )

    def test_parent_cas_conflict_keeps_child_and_edges_unchanged(self):
        self.with_two_parents()
        change = self.prepared("stale-head")
        left = self.db.artifacts.get("left")
        self.db.artifacts.commit(
            revise(left, {"level": "impression", "text": "changed"}),
            expected_revision=1,
            op="revise",
            source_ids=(self.source.id,),
        )
        with self.assertRaises(VersionError):
            self.db.artifacts.commit_tree_change(change)
        self.assertEqual(self.db.artifacts.get("child").header.revision, 1)
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), ["left", "right"])

    def test_writer_repairs_cache_after_commit_failure(self):
        self.with_two_parents()
        cache = Cache(self.db.artifacts)
        cache.load()
        writer = MaintenanceWriter(self.db.artifacts, cache)
        change = self.prepared("repair")
        with (
            patch.object(cache, "put", side_effect=RuntimeError("cache unavailable")),
            self.assertRaises(RuntimeError),
        ):
            writer.execute_tree(change)
        self.assertEqual(writer.pending(), 1)
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), [])
        self.assertEqual(writer.retry_writebacks(), 1)
        self.assertIsNone(cache.get("left"))
        self.assertEqual(cache.get("child").payload["text"], "corrected")
        self.assertEqual(writer.execute_tree(change), 0)

    def test_failed_cache_removal_reloads_retired_parent_before_reader(self):
        self.with_two_parents()
        cache = Cache(self.db.artifacts)
        cache.load()
        writer = MaintenanceWriter(self.db.artifacts, cache)
        with (
            patch.object(cache, "remove", side_effect=RuntimeError("remove failed")),
            self.assertRaises(RuntimeError),
        ):
            writer.execute_tree(self.prepared("remove-failure"))
        self.assertIsNone(cache.get("left"))
        self.assertIsNone(cache.get("right"))
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), [])

    def test_legacy_database_keeps_edges_without_fabricating_history(self):
        path = str(Path(self.tmp.name) / "legacy.db")
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE edges (src TEXT, dst TEXT, kind TEXT, weight REAL, "
            "PRIMARY KEY(src, dst, kind))"
        )
        conn.execute("INSERT INTO edges VALUES('old', 'child', 'tree_child:old', 1.0)")
        conn.commit()
        conn.close()
        legacy = open_store(path)
        self.addCleanup(legacy.close)
        self.assertEqual(legacy.artifacts.tree_parents("child", 8), ["old"])
        self.assertEqual(
            legacy.conn.execute("SELECT COUNT(*) FROM tree_change_log").fetchone()[0], 0
        )
        self.assertEqual(legacy.artifacts.current_evidence_ids("child", 8), [])

    def test_touched_legacy_edge_without_evidence_is_not_trusted(self):
        old_parent = self.memory("old-parent", "impression")
        self.db.artifacts.upsert(
            old_parent
        )  # Legacy seed has no current-version evidence.
        child = self.memory("new-child")
        self.save(child)
        self.db.artifacts.add_edge(
            "old-parent", "new-child", "tree_child:old-parent", 1.0
        )
        with self.assertRaisesRegex(ValueError, "Source evidence"):
            self.tree.add_under(revise(child), ("old-parent",))
        self.assertEqual(self.db.artifacts.get("new-child").header.revision, 1)
        self.assertEqual(self.db.artifacts.current_evidence_ids("old-parent", 8), [])
        self.assertEqual(self.db.artifacts.tree_parents("new-child", 8), ["old-parent"])

    def test_privacy_tightening_can_retire_old_parent_and_remove_link(self):
        parent = make(
            "memory",
            {"level": "impression", "text": "public old"},
            id="public-parent",
            subject_id="u1",
            scope="shared",
            shareable="shareable",
            lineage={"sources": (self.source.id,)},
        )
        child = make(
            "memory",
            {"level": "fact", "text": "public old"},
            id="public-child",
            subject_id="u1",
            scope="shared",
            shareable="shareable",
            lineage={"sources": (self.source.id,)},
        )
        self.save(parent)
        self.save(child)
        self.db.artifacts.add_edge(
            "public-parent", "public-child", "tree_child:public-parent", 1.0
        )
        change = TreeChange(
            "privacy-tightening",
            (
                TreeRevision(
                    revise(child, scope="private", shareable="private_only"),
                    1,
                    (self.source.id,),
                ),
                TreeRevision(revise(parent, state="forgotten"), 1, (self.source.id,)),
            ),
            (("public-child", 1), ("public-parent", 1)),
            (("public-child", self.db.artifacts.tree_snapshot("public-child")),),
            (("public-child", ()),),
            "revise",
            "review",
        )
        self.assertTrue(self.db.artifacts.commit_tree_change(change))
        self.assertEqual(self.db.artifacts.tree_parents("public-child", 8), [])
        self.assertEqual(self.db.artifacts.get("public-child").header.scope, "private")
        self.assertEqual(
            self.db.artifacts.get("public-parent").header.state, "forgotten"
        )

    def test_source_subject_mismatch_rejects_edge_and_revision(self):
        parent = make(
            "memory",
            {"level": "impression", "text": "wrong subject"},
            id="other-parent",
            subject_id="u2",
            lineage={"sources": (self.source.id,)},
        )
        child = make(
            "memory",
            {"level": "fact", "text": "wrong subject"},
            id="other-child",
            subject_id="u2",
            lineage={"sources": (self.source.id,)},
        )
        self.save(parent)
        with self.assertRaisesRegex(ValueError, "Source subject"):
            self.tree.add_under(child, (parent.header.id,))
        self.assertIsNone(self.db.artifacts.get(child.header.id))

    def test_cannot_attach_private_child_to_public_parent_or_form_long_cycle(self):
        parent = self.memory("parent", "impression")
        private = make(
            "memory",
            {"level": "fact", "text": "private"},
            id="private",
            subject_id="u1",
            shareable="shareable",
            lineage={"sources": (self.source.id,)},
        )
        self.save(parent)
        with self.assertRaises(ValueError):
            self.tree.add_under(private, ("parent",))
        self.assertIsNone(self.db.artifacts.get("private"))
        for idx in range(5):
            self.tree.add_under(self.memory(f"n{idx}"), (f"n{idx - 1}",) if idx else ())
        old = self.db.artifacts.get("n0")
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.tree.add_under(revise(old), ("n4",))
        self.assertEqual(self.db.artifacts.get("n0").header.revision, 1)

    def test_cache_failure_repairs_from_committed_head(self):
        self.save(self.memory("parent", "impression"))
        with (
            patch.object(
                self.cache, "put", side_effect=RuntimeError("cache unavailable")
            ),
            self.assertRaises(RuntimeError),
        ):
            self.tree.add_under(self.memory("child"), ("parent",))
        self.assertIsNotNone(self.db.artifacts.get("child"))
        self.assertEqual(self.tree.parents("child"), ("parent",))
        # A subsequent call can reload the current committed view rather than a stale plan.
        self.cache.load()
        self.assertEqual(self.cache.get("child"), self.db.artifacts.get("child"))


if __name__ == "__main__":
    unittest.main()
