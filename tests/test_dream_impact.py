"""Bounded, read-only correction impact audit over persisted dependencies."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.artifact import Lineage, make, revise
from core.domain.memory.tree import tree_child_kind
from core.source import Source
from maintain.dream_impact import inspect_correction_impact
from maintain.dream_reconcile import prepare_source_correction
from store import open_store


class DreamImpactTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = open_store(str(Path(directory.name) / "memory.db"))
        self.addCleanup(self.db.close)
        self.db.sources.append_sources([
            Source("s1", "t1", "private:u", "u", "user", "original", "2026-11-01T10:00:00+08:00")
        ])
        self.node("child")

    def node(self, node_id: str, *, derived: tuple[str, ...] = (),
             sources: tuple[str, ...] = ("s1",), subject: str = "u", scope: str = "private",
             level: str = "fact", text: str | None = None) -> None:
        art = make("memory", {"level": level, "text": text or node_id}, id=node_id,
                   subject_id=subject, scope=scope,
                   lineage=Lineage(sources=sources, derived_from=derived))
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=sources)

    def link(self, parent: str, child: str) -> None:
        self.db.artifacts.add_edge(parent, child, tree_child_kind(parent), 1.0)

    def inspect(self, **limits):
        return inspect_correction_impact(self.db.artifacts, self.db.sources,
                                         "child", **limits)

    def test_two_parents_and_shared_ancestor_have_one_bounded_read_only_impact(self) -> None:
        self.node("parent_a", derived=("child",))
        self.node("parent_b", derived=("child",))
        self.node("root", derived=("parent_a", "parent_b"))
        for parent, child in (("parent_a", "child"), ("parent_b", "child"),
                              ("root", "parent_a"), ("root", "parent_b")):
            self.link(parent, child)
        before = self.db.ledger.last_hash()
        edges = self.db.artifacts.tree_parents("child", 8)

        report = self.inspect()

        self.assertEqual(report, self.inspect())
        self.assertEqual(report.affected_ids, ("parent_a", "parent_b", "root"))
        self.assertEqual(report.blockers, ())
        self.assertFalse(report.truncated)
        self.assertLessEqual(report.visits, 32)
        self.assertEqual(self.db.ledger.last_hash(), before)
        self.assertEqual(self.db.artifacts.tree_parents("child", 8), edges)

    def test_multi_parent_source_correction_is_reported_but_not_committed(self) -> None:
        self.db.sources.append_sources([
            Source("s_correction", "t2", "private:u", "u", "user",
                   "更正：只是短期出差", "2026-11-02T10:00:00+08:00", reply_to="s1")
        ])
        for parent_id in ("a_parent", "b_parent"):
            self.node(parent_id, derived=("child",), level="impression", text="child")
            self.link(parent_id, "child")
        before = self.db.ledger.last_hash()

        self.assertIsNone(prepare_source_correction(
            self.db.artifacts, self.db.sources, self.db.artifacts, "child", "s_correction"))
        report = self.inspect()
        self.assertEqual(report.affected_ids, ("a_parent", "b_parent"))
        self.assertEqual(report.blockers, ())
        self.assertEqual(self.db.ledger.last_hash(), before)
        self.assertEqual(self.db.artifacts.get("child").header.revision, 1)

    def test_incomplete_or_cross_identity_paths_defer_without_fake_links(self) -> None:
        self.node("edge_only")
        self.node("lineage_only", derived=("child",))
        self.node("other_user", derived=("child",), subject="v")
        self.node("missing_source", derived=("child",), sources=("unavailable",))
        for node_id in ("edge_only", "other_user", "missing_source", "gone"):
            self.link(node_id, "child")
        before = self.db.ledger.last_hash()

        report = self.inspect()

        self.assertIn("edge_without_lineage", report.blockers)
        self.assertIn("lineage_without_edge", report.blockers)
        self.assertIn("identity_mismatch", report.blockers)
        self.assertIn("missing_evidence", report.blockers)
        self.assertIn("missing_parent", report.blockers)
        self.assertEqual(self.db.ledger.last_hash(), before)
        self.assertIsNone(self.db.artifacts.get("gone"))

    def test_cycle_and_each_budget_return_conservative_truncation(self) -> None:
        self.node("a", derived=("child",))
        self.node("b", derived=("a",))
        self.link("a", "child")
        self.link("b", "a")
        self.db.artifacts.add_edge("child", "b", tree_child_kind("child"), 1.0)
        child = self.db.artifacts.get("child")
        self.db.artifacts.commit(revise(child, lineage=Lineage(sources=("s1",),
                                                             derived_from=("b",))),
                                 expected_revision=1, op="revise", source_ids=("s1",))
        self.assertIn("cycle", self.inspect().blockers)
        depth = self.inspect(max_depth=1)
        self.assertTrue(depth.truncated)
        self.assertIn("depth_limit", depth.blockers)
        visits = self.inspect(max_visits=1)
        self.assertTrue(visits.truncated)
        self.assertIn("visit_limit", visits.blockers)
        self.node("c", derived=("child",))
        self.link("c", "child")
        branches = self.inspect(max_parents=1)
        self.assertTrue(branches.truncated)
        self.assertIn("branch_limit", branches.blockers)

    def test_shared_ancestor_cycle_is_detected_across_distinct_paths(self) -> None:
        self.node("a", derived=("child",))
        self.node("b", derived=("child", "root"))
        self.node("root", derived=("a", "b"))
        for parent, child in (("a", "child"), ("b", "child"),
                              ("root", "a"), ("root", "b"), ("b", "root")):
            self.link(parent, child)
        report = self.inspect()
        self.assertIn("cycle", report.blockers)
        self.assertLessEqual(report.visits, 32)

    def test_missing_root_or_proof_and_legacy_lineage_cannot_be_marked_ready(self) -> None:
        self.assertEqual(inspect_correction_impact(self.db.artifacts, self.db.sources,
                                                   "nonexistent").blockers, ("invalid_child",))
        self.node("bad_source", derived=("child",), sources=("s_other",))
        self.link("bad_source", "child")
        self.assertIn("missing_evidence", self.inspect().blockers)
        # Old malformed lineage must not invent a valid reverse dependency.
        self.db.conn.execute("UPDATE nodes SET lineage = ? WHERE id = ?",
                             ('{"derived_from":"child"}', "bad_source"))
        report = self.inspect()
        self.assertIn("edge_without_lineage", report.blockers)
        self.assertNotIn("bad_source", report.affected_ids)

    def test_parent_with_unrelated_evidence_or_visibility_is_not_safe(self) -> None:
        self.db.sources.append_sources([
            Source("s2", "t2", "private:u", "u", "user", "unrelated", "2026-11-01T11:00:00+08:00")
        ])
        self.node("unrelated", derived=("child",), sources=("s2",))
        self.node("other_scope", derived=("child",), scope="shared")
        self.link("unrelated", "child")
        self.link("other_scope", "child")
        report = self.inspect()
        self.assertIn("evidence_mismatch", report.blockers)
        self.assertIn("identity_mismatch", report.blockers)
        self.assertEqual(report.affected_ids, ())

    def test_current_lineage_only_and_malformed_json_cannot_create_dependencies(self) -> None:
        self.node("parent", derived=("child",))
        self.link("parent", "child")
        self.assertEqual(self.db.artifacts.active_dependents("child", 1), ["parent"])
        parent = self.db.artifacts.get("parent")
        self.db.artifacts.commit(revise(parent, lineage=Lineage(sources=("s1",))),
                                 expected_revision=1, op="revise", source_ids=("s1",))
        self.assertEqual(self.db.artifacts.active_dependents("child", 1), [])
        self.assertIn("edge_without_lineage", self.inspect().blockers)
        self.db.conn.execute("UPDATE nodes SET lineage = ? WHERE id = ?",
                             ('{broken-json', "parent"))
        self.assertEqual(self.db.artifacts.active_dependents("child", 1), [])
        with self.assertRaises(ValueError):
            self.db.artifacts.active_dependents("child", 0)

    def test_child_without_current_evidence_does_not_enumerate_parents(self) -> None:
        self.node("parent", derived=("child",))
        self.link("parent", "child")
        self.db.conn.execute("DELETE FROM artifact_evidence WHERE entity = ?", ("child",))
        report = self.inspect()
        self.assertEqual(report.affected_ids, ())
        self.assertIn("missing_version_evidence", report.blockers)

    def test_lineage_source_without_current_version_evidence_is_not_verified(self) -> None:
        self.node("parent", derived=("child",))
        self.link("parent", "child")
        self.db.conn.execute("DELETE FROM artifact_evidence WHERE entity = ?", ("parent",))
        report = self.inspect()
        self.assertIn("missing_version_evidence", report.blockers)
        self.assertNotIn("parent", report.affected_ids)

    def test_foreign_user_source_cannot_support_a_same_subject_hierarchy(self) -> None:
        self.db.sources.append_sources([
            Source("s_foreign", "t_other", "private:v", "v", "user", "foreign", "2026-11-01T11:00:00+08:00")
        ])
        self.node("foreign_parent", derived=("child",), sources=("s1", "s_foreign"))
        self.link("foreign_parent", "child")
        report = self.inspect()
        self.assertIn("evidence_identity", report.blockers)
        self.assertNotIn("foreign_parent", report.affected_ids)

    def test_inactive_parent_is_not_silently_accepted(self) -> None:
        self.node("parent", derived=("child",))
        self.link("parent", "child")
        parent = self.db.artifacts.get("parent")
        self.db.artifacts.commit(revise(parent, state="forgotten"),
                                 expected_revision=1, op="revise", source_ids=("s1",))
        self.assertIn("stale_edge", self.inspect().blockers)


if __name__ == "__main__":
    unittest.main()
