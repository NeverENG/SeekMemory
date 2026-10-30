"""Tree ancestry is bounded and follows only encoded parent edges."""

from __future__ import annotations

import unittest

from core.domain.memory.tree import ancestor_ids, parent_id, tree_child_kind


class Edges:
    def __init__(self, rows: dict[str, list[tuple[str, str, float]]]) -> None:
        self.rows = rows
        self.reads: list[str] = []

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        self.reads.append(node_id)
        return self.rows.get(node_id, [])


class TreeDomainTest(unittest.TestCase):
    def test_parent_uses_existing_encoded_edge_not_other_edge_kinds(self) -> None:
        edges = Edges({"child": [
            ("other", "causal", 1.0),
            ("own-child", tree_child_kind("child"), 1.0),
            ("wrong", tree_child_kind("parent"), 1.0),
            ("parent", tree_child_kind("parent"), 1.0),
        ]})
        self.assertEqual(parent_id("child", edges), "parent")
        self.assertIsNone(parent_id("missing", edges))
        self.assertIsNone(parent_id("", edges))
        self.assertEqual(edges.reads, ["child", "missing"])

    def test_ambiguous_parent_does_not_choose_an_arbitrary_branch(self) -> None:
        edges = Edges({"child": [
            ("a", tree_child_kind("a"), 1.0),
            ("b", tree_child_kind("b"), 1.0),
        ]})
        self.assertIsNone(parent_id("child", edges))
        self.assertEqual(ancestor_ids("child", edges), ())

    def test_ancestors_stop_at_missing_parent_depth_and_cycle(self) -> None:
        edges = Edges({
            "leaf": [("middle", tree_child_kind("middle"), 1.0)],
            "middle": [("root", tree_child_kind("root"), 1.0)],
            "root": [("leaf", tree_child_kind("leaf"), 1.0)],
        })
        self.assertEqual(ancestor_ids("leaf", edges), ("middle", "root"))
        edges.reads.clear()
        self.assertEqual(ancestor_ids("leaf", edges, max_depth=1), ("middle",))
        self.assertEqual(edges.reads, ["leaf"])
        self.assertEqual(ancestor_ids("unknown", edges), ())
        with self.assertRaises(ValueError):
            ancestor_ids("leaf", edges, max_depth=0)
