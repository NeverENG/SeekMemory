"""Offline Source-backed child correction and dependent-parent safety slice."""
from __future__ import annotations

import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.budget import ContextBudget
from core.artifact import Lineage, make, revise
from core.domain.memory.tree import tree_child_kind
from core.domain.memory.versioning import VersionError
from core.graph import Graph
from core.source import Source
from maintain.dream_reconcile import prepare_source_correction
from maintain.writer import MaintenanceWriter
from services.recall_service import RecallService
from services.tree_service import TreeService
from store import open_store
from store.cache import Cache


class DreamCorrectionSliceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.db = open_store(str(Path(self.directory.name) / "memory.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.original = Source(
            "s_original", "t1", "bot:FriendMessage:u1", "u1", "user",
            "我今天在北京出差", "2026-11-01T10:00:00+08:00",
        )
        self.correction = Source(
            "s_correction", "t2", self.original.session_id, "u1", "user",
            "更正：我当时只是在北京出差，不是常住北京", "2026-11-02T10:00:00+08:00",
            reply_to=self.original.id,
        )
        self.db.sources.append_sources([self.original, self.correction])
        self.child = self.seed(make(
            "memory", {"level": "fact", "text": "我常住北京"}, id="child",
            subject_id="u1", lineage=Lineage(sources=(self.original.id,)),
        ))
        self.parent = self.seed(make(
            "memory", {"level": "impression", "text": "我常住北京"}, id="parent",
            subject_id="u1", lineage=Lineage(sources=(self.original.id,), derived_from=(self.child.header.id,)),
        ))
        self.db.artifacts.add_edge(self.parent.header.id, self.child.header.id,
                                   tree_child_kind(self.parent.header.id), 1.0)

    def seed(self, artifact):
        self.db.artifacts.commit(artifact, expected_revision=0, op="create",
                                 source_ids=artifact.header.lineage.sources)
        self.cache.put(artifact)
        return artifact

    def plan(self):
        return prepare_source_correction(
            self.db.artifacts, self.db.sources, self.db.artifacts,
            self.child.header.id, self.correction.id,
        )

    def recall(self, cache: Cache | None = None) -> RecallService:
        view = cache if cache is not None else self.cache
        return RecallService(
            cache=view, graph=Graph(self.db.artifacts),
            artifacts=self.db.artifacts, sources=self.db.sources,
            budget=ContextBudget(injection_chars=600),
            config=lambda key, default: {"source_recall_enabled": False, "recall_k": 2}.get(key, default),
            owner_umo=lambda: self.original.session_id,
            tree=TreeService(self.db.artifacts, view), tree_enabled=True,
        )

    def test_explicit_correction_revises_child_and_retires_unsupported_parent_atomically(self) -> None:
        plan = self.plan()
        self.assertIsNotNone(plan)
        self.assertEqual(self.db.artifacts.get("child"), self.child)  # planning never writes
        self.assertEqual(self.db.artifacts.get("parent"), self.parent)
        self.assertEqual(MaintenanceWriter(self.db.artifacts, self.cache).execute(plan), 2)
        child, parent = self.db.artifacts.get("child"), self.db.artifacts.get("parent")
        self.assertEqual((child.header.revision, child.payload["text"]), (2, self.correction.text))
        self.assertEqual(child.header.lineage.sources, (self.original.id, self.correction.id))
        self.assertEqual((parent.header.revision, parent.header.state), (2, "forgotten"))
        self.assertIsNone(self.cache.get(parent.header.id))
        self.assertEqual([row["revision"] for row in self.db.artifacts.history("child")], [1, 2])
        self.assertEqual([row["revision"] for row in self.db.artifacts.history("parent")], [1, 2])
        self.assertIsNone(self.plan())  # same input cannot multiply versions

    def test_source_correction_remains_safe_through_read_only_recall(self) -> None:
        service = self.recall()
        old_block, old_info = service.query("我常住北京", self.original.session_id, True, "u1")
        self.assertIn("常住北京", old_block)
        self.assertIn("parent", old_info["picked_ids"])

        self.assertEqual(MaintenanceWriter(self.db.artifacts, self.cache).execute(self.plan()), 2)
        ledger_hash = self.db.ledger.last_hash()
        edges = self.db.artifacts.tree_children("parent", 8)
        source = self.db.sources.sources_by_ids([self.original.id, self.correction.id])
        corrected, info = service.query("我在北京出差", self.original.session_id, True, "u1")
        self.assertIn("child", info["picked_ids"])
        self.assertNotIn("parent", info["picked_ids"])
        self.assertIn("北京出差", corrected)
        self.assertIn("不是常住北京", corrected)
        self.assertNotIn("我常住北京", corrected)
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)
        self.assertEqual(self.db.artifacts.tree_children("parent", 8), edges)
        self.assertEqual(self.db.sources.sources_by_ids([self.original.id, self.correction.id]), source)
        self.assertIsNone(self.plan())
        reloaded_cache = Cache(self.db.artifacts)
        reloaded_cache.load()
        self.assertIsNone(reloaded_cache.get("parent"))
        reloaded, reloaded_info = self.recall(reloaded_cache).query(
            "我在北京出差", self.original.session_id, True, "u1")
        self.assertIn("child", reloaded_info["picked_ids"])
        self.assertNotIn("parent", reloaded_info["picked_ids"])
        self.assertNotIn("我常住北京", reloaded)
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)

    def test_failed_second_write_rolls_back_both_and_retries_exact_plan(self) -> None:
        writer = MaintenanceWriter(self.db.artifacts, self.cache)
        plan = self.plan()
        original_commit = self.db.artifacts._commit_conn
        attempts = 0

        def fail_second(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError("second commit failed")
            return original_commit(*args, **kwargs)

        with patch.object(self.db.artifacts, "_commit_conn", side_effect=fail_second):
            with self.assertRaises(OSError):
                writer.execute(plan)
        self.assertEqual(self.db.artifacts.get("child"), self.child)
        self.assertEqual(self.db.artifacts.get("parent"), self.parent)
        self.assertEqual(self.cache.get("child"), self.child)
        self.assertEqual(self.cache.get("parent"), self.parent)
        ledger_hash = self.db.ledger.last_hash()
        still_old, old_info = self.recall().query(
            "我常住北京", self.original.session_id, True, "u1")
        self.assertIn("parent", old_info["picked_ids"])
        self.assertIn("常住北京", still_old)
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)
        self.assertEqual(writer.retry_writebacks(), 2)
        self.assertEqual((self.db.artifacts.get("child").header.revision,
                          self.db.artifacts.get("parent").header.state), (2, "forgotten"))

    def test_concurrent_parent_revision_rejects_both_planned_writes(self) -> None:
        plan = self.plan()
        newer = revise(self.parent, payload={"level": "impression", "text": "经人工核对的其他结论"})
        self.db.artifacts.commit(newer, expected_revision=1, op="revise",
                                 source_ids=newer.header.lineage.sources)
        self.cache.put(newer)
        with self.assertRaises(VersionError):
            MaintenanceWriter(self.db.artifacts, self.cache).execute(plan)
        self.assertEqual(self.db.artifacts.get("child"), self.child)
        self.assertEqual(self.db.artifacts.get("parent"), newer)
        self.assertEqual(self.cache.get("child"), self.child)

    def test_no_parent_or_unconfirmed_rewrite_does_not_change_child(self) -> None:
        orphan = self.seed(make(
            "memory", {"level": "fact", "text": "我常住北京"}, id="orphan",
            subject_id="u1", lineage=Lineage(sources=(self.original.id,)),
        ))
        self.assertIsNone(prepare_source_correction(
            self.db.artifacts, self.db.sources, self.db.artifacts,
            orphan.header.id, self.correction.id,
        ))
        unconfirmed = Source("s_unconfirmed", "t4", self.original.session_id, "u1", "user",
                             "我现在搬去上海了", "2026-11-02T12:00:00+08:00",
                             reply_to=self.original.id)
        self.db.sources.append_sources([unconfirmed])
        self.assertIsNone(prepare_source_correction(
            self.db.artifacts, self.db.sources, self.db.artifacts, "child", unconfirmed.id))
        self.assertEqual(self.db.artifacts.get("child"), self.child)

    def test_unlinked_dependent_parent_also_blocks_partial_correction(self) -> None:
        self.seed(make(
            "memory", {"level": "impression", "text": "我常住北京"}, id="unlinked_parent",
            subject_id="u1", lineage=Lineage(sources=(self.original.id,), derived_from=("child",)),
        ))
        self.assertIsNone(self.plan())
        self.assertEqual(self.db.artifacts.get("child"), self.child)
        self.assertEqual(self.db.artifacts.get("parent"), self.parent)

    def test_ambiguous_parent_and_unattributable_correction_do_not_prepare_writes(self) -> None:
        unrelated = Source("s_unrelated", "t3", "bot:FriendMessage:u2", "u2", "user",
                           "更正：我不是常住北京", "2026-11-02T12:00:00+08:00",
                           reply_to=self.original.id)
        other_session = Source("s_other_session", "t5", "bot:GroupMessage:g1", "u1", "user",
                               "更正：我不是常住北京", "2026-11-02T12:00:00+08:00",
                               reply_to=self.original.id)
        self.db.sources.append_sources([unrelated, other_session])
        for source_id in (unrelated.id, other_session.id, "s_missing"):
            self.assertIsNone(prepare_source_correction(
                self.db.artifacts, self.db.sources, self.db.artifacts, "child", source_id))
        other = self.seed(make(
            "memory", {"level": "impression", "text": "我常住北京"}, id="other_parent",
            subject_id="u1", lineage=Lineage(sources=(self.original.id,), derived_from=("child",)),
        ))
        self.db.artifacts.add_edge(other.header.id, "child", tree_child_kind(other.header.id), 1.0)
        self.assertIsNone(self.plan())
        self.assertEqual(self.db.artifacts.get("child"), self.child)
        self.assertEqual(self.db.artifacts.get("parent"), self.parent)


if __name__ == "__main__":
    unittest.main()
