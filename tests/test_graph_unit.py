"""Exercise graph policy with a small storage-port fake.

通过小型存储端口替身验证图规则。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import Artifact, make
from core.graph import Graph

def _memory(
    text: str,
    level: str = "scene",
    scope: str = "private",
    created: str | None = None,
) -> Artifact:
    """构造一条最小合法 memory；created 不传时由 make 记当前时间。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "point",
        "chrono": "once",
        "about": "other",
    }
    header: dict[str, object] = {"scope": scope}
    if created is not None:
        header["time"] = {"created": created, "updated": created}
    return make("memory", payload, **header)


class EdgeStore:
    """Hold symmetric edge views behind the real graph port / 通过真实图端口提供对称边视图。"""

    def __init__(self):
        self.edges = {}

    def add_edge(self, src, dst, kind, weight):
        self.edges[src, dst, kind] = weight

    def edges_of(self, node_id):
        return [(dst if src == node_id else src, kind, weight)
                for (src, dst, kind), weight in self.edges.items()
                if node_id in (src, dst)]


class GraphApiTest(unittest.TestCase):
    """Exercise explicit causal edges and graph degree / 验证显式因果边及图度数。"""

    def setUp(self):
        self.graph = Graph(EdgeStore())

    def _write(self, art):
        return art

    def test_causal_interface_and_degree(self) -> None:
        """link_causal 建出的 causal 边可查；degree 统计全部关系边。"""
        first = self._write(_memory("他今天淋了雨",
                                    created="2026-10-18T20:00:00"))
        second = self._write(_memory("他第二天发烧了",
                                     created="2026-10-19T20:00:00"))

        self.graph.link_causal(first.header.id, second.header.id, 0.8)
        self.assertIn((second.header.id, 0.8),
                      self.graph.neighbours(first.header.id))
        self.assertEqual(self.graph.degree(first.header.id), 1)
        self.assertEqual(self.graph.degree(""), 0)
        self.assertEqual(Graph(None).degree(first.header.id), 0)

    def test_neighbours_filter_kinds_and_keep_maximum_in_stable_order(self):
        graph = self.graph
        graph.link("a", "z", "similar", 0.2)
        graph.link("a", "z", "temporal", 0.8)
        graph.link("a", "b", "causal", 0.5)
        self.assertEqual(graph.neighbours("a"), [("b", 0.5), ("z", 0.8)])
        self.assertEqual(graph.neighbours("a", ("similar",)), [("z", 0.2)])

    def test_invalid_edges_leave_the_store_unchanged(self):
        for src, dst, kind in (("a", "a", "similar"), ("", "b", "causal"), ("a", "b", "unknown")):
            with self.subTest(src=src, dst=dst, kind=kind), self.assertRaises(ValueError):
                self.graph.link(src, dst, kind, 1.0)
        self.assertEqual(self.graph.degree("a"), 0)


if __name__ == "__main__":
    unittest.main()
