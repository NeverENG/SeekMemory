"""Bounded tree recall and guarded integration / 有界树召回及安全集成。"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.budget import ContextBudget
from core.artifact import Lineage, make, revise
from core.graph import Graph
from core.source import Source
from recall.tree_query import TreeQueryLimits, expand_tree
from services.recall_service import RecallService
from services.tree_service import TreeService
from store import open_store
from store.cache import Cache


class TreeQueryTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.tree = TreeService(self.db.artifacts, self.cache)
        self.session = "bot:FriendMessage:u"
        self.db.sources.append_sources([Source("s1", "t", self.session, "u", "user", "proof", "t")])
        self.nodes = []

    def node(self, text, *, subject="u", scope="private", evidence=True, level="scene", node_id=None):
        art = make("memory", {"text": text, "level": level}, subject_id=subject,
                   scope=scope, lineage=Lineage(("s1",) if evidence else ()),
                   **({"id": node_id} if node_id else {}))
        self.db.artifacts.commit(art, expected_revision=0, op="create",
                                 source_ids=("s1",) if evidence else ())
        self.cache.put(art)
        self.nodes.append(art)
        return art

    def edge(self, child, parent):
        self.db.artifacts.add_edge(parent.header.id, child.header.id,
                                   "tree_child:" + parent.header.id, 1.0)

    def expand(self, anchor, limits=TreeQueryLimits()):
        return expand_tree([anchor], self.nodes, self.tree, self.db.artifacts,
                           self.db.sources, limits)

    def test_up_down_siblings_and_cycle_are_bounded(self):
        impression = self.node("impression", level="impression")
        scene = self.node("scene")
        detail = self.node("detail", level="fact")
        other = self.node("sibling", level="fact")
        self.edge(scene, impression)
        self.edge(detail, scene)
        self.edge(other, scene)
        self.edge(impression, detail)  # Malformed cycle must not recurse forever.
        result = self.expand(detail)
        self.assertEqual(result.ids, (scene.header.id, impression.header.id, other.header.id))
        self.assertGreater(result.rejected.get("cycle", 0), 0)
        root = self.node("independent root")
        leaf = self.node("independent leaf")
        self.edge(leaf, root)
        self.assertEqual(self.expand(root, TreeQueryLimits(depth=3, children=1)).children, 1)

    def test_two_parent_paths_expand_depth_and_branch_with_hard_limits(self):
        top = self.node("top", level="impression")
        other = self.node("other", level="scene")
        first = self.node("first", level="scene")
        second = self.node("second", level="scene")
        leaf = self.node("leaf", level="fact")
        side = self.node("side detail", level="fact")
        for child, parent in ((first, top), (second, top), (leaf, first),
                              (leaf, second), (side, other), (other, top)):
            self.edge(child, parent)
        self.assertEqual(set(self.tree.parents(leaf.header.id)),
                         {first.header.id, second.header.id})
        result = self.expand(leaf, TreeQueryLimits(depth=4, total=8, visits=48))
        self.assertIn(top.header.id, result.ids)
        self.assertIn(first.header.id, result.ids)
        self.assertIn(second.header.id, result.ids)
        self.assertIn(other.header.id, result.ids)
        self.assertIn(side.header.id, result.ids)
        bounded = self.expand(leaf, TreeQueryLimits(depth=1, visits=3, total=2))
        self.assertLessEqual(bounded.visits, 3)
        self.assertLessEqual(len(bounded.ids), 2)
        self.assertNotIn(top.header.id, bounded.ids)
        one_hop = self.expand(leaf, TreeQueryLimits(depth=1, visits=48))
        self.assertNotIn(top.header.id, one_hop.ids)
        self.assertNotIn(side.header.id, one_hop.ids)
        self.edge(top, leaf)  # Cyclic multi-parent data must still terminate.
        self.assertLessEqual(self.expand(leaf, TreeQueryLimits(visits=5)).visits, 5)

    def test_retired_edges_do_not_hide_later_valid_siblings_or_parents(self):
        old_parent = self.node("old parent", level="impression", node_id="a_parent")
        live_parent = self.node("live parent", level="impression", node_id="z_parent")
        old_child = self.node("old sibling", level="fact", node_id="a_sibling")
        anchor = self.node("anchor", level="fact", node_id="m_anchor")
        live_sibling = self.node("live sibling", level="fact", node_id="z_sibling")
        self.edge(anchor, old_parent)
        self.edge(anchor, live_parent)
        self.edge(old_child, live_parent)
        self.edge(live_sibling, live_parent)
        for art in (old_parent, old_child):
            inactive = revise(art, state="forgotten")
            self.db.artifacts.commit(inactive, expected_revision=1, op="revise",
                                     source_ids=("s1",))
        result = self.expand(anchor, TreeQueryLimits(parents=1, siblings=1, depth=2))
        self.assertIn(live_parent.header.id, result.ids)
        self.assertIn(live_sibling.header.id, result.ids)
        self.assertNotIn(old_parent.header.id, result.ids)
        self.assertNotIn(old_child.header.id, result.ids)

    def test_two_sources_support_one_parent_and_multiple_parent_paths(self):
        self.db.sources.append_sources([Source("s2", "t2", self.session, "u", "user", "other", "t")])
        anchor = self.node("anchor")
        first = self.node("first conclusion", level="impression")
        second = make("memory", {"text": "combined conclusion", "level": "impression"},
                      subject_id="u", lineage=Lineage(("s1", "s2")))
        self.db.artifacts.commit(second, expected_revision=0, op="create",
                                 source_ids=("s1", "s2"))
        self.cache.put(second)
        self.nodes.append(second)
        self.edge(anchor, first)
        self.edge(anchor, second)
        result = self.expand(anchor)
        self.assertIn(first.header.id, result.ids)
        self.assertIn(second.header.id, result.ids)
        self.assertEqual(result.parents, 2)

    def test_relevance_and_path_support_rank_without_bypassing_evidence(self):
        anchor = self.node("anchor")
        weak = self.node("unrelated dull", level="scene")
        relevant = self.node("rocket rocket", level="scene")
        self.edge(anchor, weak)
        self.edge(anchor, relevant)
        result = expand_tree([anchor], self.nodes, self.tree, self.db.artifacts,
                             self.db.sources, text="rocket")
        self.assertLess(result.ids.index(relevant.header.id), result.ids.index(weak.header.id))
        self.assertNotIn("rocket", str(result.info()))

    def test_identity_evidence_and_stale_cache_rejected_without_sibling_leak(self):
        anchor = self.node("anchor")
        bad_parent = self.node("other subject", subject="v")
        sibling = self.node("sibling")
        self.edge(anchor, bad_parent)
        self.edge(sibling, bad_parent)
        result = self.expand(anchor)
        self.assertEqual(result.ids, ())
        self.assertEqual(result.rejected["identity"], 1)
        other_scope = self.node("other scope", scope="shared")
        self.edge(other_scope, anchor)
        self.assertEqual(self.expand(anchor).rejected.get("identity"), 2)
        missing = self.node("missing evidence", evidence=False)
        stale = self.node("stale")
        self.edge(missing, anchor)
        self.edge(stale, anchor)
        self.db.artifacts.commit(revise(stale, {"text": "new"}),
                                 expected_revision=1, op="revise", source_ids=("s1",))
        result = self.expand(anchor)
        self.assertEqual(result.ids, ())
        self.assertEqual(result.rejected.get("evidence"), 1)
        self.assertEqual(result.rejected.get("stale"), 1)

    def test_service_expands_two_parents_without_extra_writes(self):
        left = self.node("left context", level="scene")
        right = self.node("right context", level="impression")
        anchor = self.node("needle anchor unique", level="fact")
        self.tree.add_under(anchor, (left.header.id, right.header.id))
        service = RecallService(
            cache=self.cache, graph=self.graph, artifacts=self.db.artifacts,
            sources=self.db.sources, budget=ContextBudget(injection_chars=600),
            config=lambda key, default: {"source_recall_enabled": False, "recall_k": 3}.get(key, default),
            owner_umo=lambda: self.session, tree=self.tree, tree_enabled=True,
        )
        with patch.object(self.db.artifacts, "commit", side_effect=AssertionError("write")):
            _block, info = service.query("needle anchor unique", self.session, True, "u")
        self.assertIn(left.header.id, info["picked_ids"])
        self.assertIn(right.header.id, info["picked_ids"])
        self.assertIn(anchor.header.id, info["picked_ids"])
        self.assertGreaterEqual(info["tree"]["parents"], 1)

    def test_tree_added_cross_session_text_still_passes_disclosure(self):
        parent = self.node("parent private never quote", scope="shared", level="impression")
        anchor = self.node("needle shared query", scope="shared", level="fact")
        self.edge(anchor, parent)
        service = RecallService(
            cache=self.cache, graph=self.graph, artifacts=self.db.artifacts,
            sources=self.db.sources, budget=ContextBudget(injection_chars=600),
            config=lambda key, default: {"source_recall_enabled": False, "recall_k": 3}.get(key, default),
            owner_umo=lambda: self.session, tree=self.tree, tree_enabled=True,
        )
        block, info = service.query("needle shared query", "other:FriendMessage:u", True, "u")
        self.assertIn(parent.header.id, info["picked_ids"])
        self.assertNotIn("parent private never quote", block)
        self.assertNotEqual(info["disclosure"].get(parent.header.id), "full")

    def test_legacy_only_parent_forces_flat_fallback_without_repair(self):
        anchor = self.node("unique topic")
        parent = self.node("legacy parent")
        self.db.conn.execute("UPDATE nodes SET parent = ? WHERE id = ?",
                             (parent.header.id, anchor.header.id))
        service = RecallService(
            cache=self.cache, graph=self.graph, artifacts=self.db.artifacts,
            sources=self.db.sources, budget=ContextBudget(injection_chars=600),
            config=lambda key, default: {"source_recall_enabled": False}.get(key, default),
            owner_umo=lambda: self.session, tree=self.tree, tree_enabled=True,
        )
        with patch.object(self.db.artifacts, "add_edge", side_effect=AssertionError("repair")):
            _block, info = service.query("unique topic", self.session, True, "u")
        self.assertEqual(info["tree"]["status"], "fallback")
        self.assertEqual(self.db.artifacts.legacy_tree_gap_count(), 1)
        self.assertEqual(info["tree"]["rejected"], {"legacy_parent_only": 1})

    def test_service_read_only_disclosure_budget_and_failure_fallback(self):
        parent = self.node("private parent unique", level="impression")
        anchor = self.node("needle anchor unique", level="fact")
        self.edge(anchor, parent)
        conf = lambda key, default: {"source_recall_enabled": False, "recall_k": 3}.get(key, default)
        def service(enabled, tree=None):
            return RecallService(cache=self.cache, graph=self.graph, artifacts=self.db.artifacts,
                                 sources=self.db.sources, budget=ContextBudget(injection_chars=200),
                                 config=conf, owner_umo=lambda: self.session,
                                 tree=tree, tree_enabled=enabled)
        flat = service(False, self.tree).query("needle anchor unique", self.session, True, "u")
        with patch.object(self.db.artifacts, "commit", side_effect=AssertionError("write")):
            block, info = service(True, self.tree).query("needle anchor unique", self.session, True, "u")
        self.assertIn(anchor.header.id, info["picked_ids"])
        self.assertIn(parent.header.id, info["picked_ids"])
        self.assertIn("tree", info)
        self.assertLessEqual(len(block), 200)
        broken = SimpleNamespace(parent_id=lambda _: (_ for _ in ()).throw(RuntimeError("broken")),
                                 children=lambda _: [])
        fallback = service(True, broken).query("needle anchor unique", self.session, True, "u")
        self.assertEqual(fallback[0], flat[0])
        self.assertEqual(fallback[1]["picked_ids"], flat[1]["picked_ids"])
        self.assertEqual(fallback[1]["tree"]["status"], "fallback")
        self.assertNotIn("tree", flat[1])
