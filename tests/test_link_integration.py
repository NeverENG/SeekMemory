"""test_link：写入时自动建联想边与全链路 fail-open。

覆盖相似边（Dice 阈值上/下）、同一天时序边、跨 scope 不连边、单节点
出度预算与重复写入幂等；graph/cache 缺失或抛异常时，写入照常完成。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make
from core.graph import Graph
from maintain.link import (
    MAX_EDGES,
    SIMILAR_BAR,
    TEMPORAL_WEIGHT,
    link_new,
    persist,
)
from recall.seed import seeds
from recall.spread import activate
from store.cache import Cache
from store import open_store


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


class _BoomCache:
    """active() 抛异常的缓存替身：put 委托真实缓存，模拟索引损坏。"""

    def __init__(self, real: Cache) -> None:
        self.real = real

    def put(self, art: Artifact) -> None:
        """保持正常写入能力。"""
        self.real.put(art)

    def active(self, family: str | None = None) -> list[Artifact]:
        """模拟缓存索引不可用。"""
        raise RuntimeError("cache index down")


class _BoomGraph:
    """link() 必抛异常的图替身：db 可读，边写入失败。"""

    def __init__(self, artifacts) -> None:
        self.artifacts = artifacts

    def link(self, *_args: object) -> None:
        """模拟边表写入失败。"""
        raise RuntimeError("edge store down")


class _LinkCase(unittest.TestCase):
    """每个用例一个临时数据库、缓存与关系图。"""

    def setUp(self) -> None:
        """创建临时库与依赖对象。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_link_")
        self.db = open_store(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, art: Artifact) -> Artifact:
        """走生产写入路径：写库 + 入缓存 + 建边。"""
        persist(art, self.db.artifacts, self.cache, self.graph)
        return art

    def _edges(self, art: Artifact) -> list[tuple[str, str, float]]:
        """该节点的全部边（出边与入边都算）。"""
        return self.db.artifacts.edges_of(art.header.id)


class SimilarEdgeTest(_LinkCase):
    """相似边：Dice 重合度过阈值才建，跨 scope 与低相似不建。"""

    def test_similar_text_links_with_dice_weight(self) -> None:
        """重合度 > 0.45 的两条记忆之间建一条 similar 边，权重即相似度。"""
        first = self._write(_memory("他今天加班到凌晨两点才回家",
                                    created="2026-10-18T20:00:00"))
        second = self._write(_memory("他今天加班到凌晨两点才回家，很累",
                                     created="2026-10-19T20:00:00"))

        edges = self._edges(second)
        self.assertEqual(len(edges), 1)
        other, kind, weight = edges[0]
        self.assertEqual((other, kind), (first.header.id, "similar"))
        self.assertGreater(weight, SIMILAR_BAR)
        self.assertLessEqual(weight, 1.0)
        self.assertIn((first.header.id, weight),
                      self.graph.neighbours(second.header.id))

    def test_low_similarity_on_different_days_makes_no_edge(self) -> None:
        """重合度为 0 且不同天时，similar 与 temporal 都不建。"""
        first = self._write(_memory("今天天气不错",
                                    created="2026-10-18T09:00:00"))
        second = self._write(_memory("楼下新开了一家面馆",
                                     created="2026-10-19T21:00:00"))

        self.assertEqual(self._edges(first), [])
        self.assertEqual(self._edges(second), [])
        self.assertEqual(self.graph.neighbours(second.header.id), [])

    def test_cross_scope_never_links(self) -> None:
        """同一个 scope 才连边：private 与 shared 的相同文本互不相连。"""
        private = self._write(_memory("他今天加班到凌晨两点才回家",
                                      scope="private",
                                      created="2026-10-18T20:00:00"))
        shared = self._write(_memory("他今天加班到凌晨两点才回家",
                                     scope="shared",
                                     created="2026-10-18T20:00:00"))

        self.assertEqual(self._edges(private), [])
        self.assertEqual(self._edges(shared), [])

    def test_same_day_makes_temporal_edge_not_similar(self) -> None:
        """不相似但同一天写入：只建 temporal 边，权重 0.3。"""
        first = self._write(_memory("今天天气不错",
                                    created="2026-10-20T09:00:00"))
        second = self._write(_memory("楼下新开了一家面馆",
                                     created="2026-10-20T21:00:00"))

        self.assertEqual(self._edges(second),
                         [(first.header.id, "temporal", TEMPORAL_WEIGHT)])
        self.assertEqual(self._edges(first),
                         [(second.header.id, "temporal", TEMPORAL_WEIGHT)])


class SpreadRecallTest(_LinkCase):
    """一跳召回：A 与 B 有边时，查询 A 能通过扩散捞回不含关键词的 B。"""

    def test_one_hop_spread_reaches_linked_neighbour(self) -> None:
        """B 不含查询关键词，但沿同一天建的 temporal 边被激活扩散捞回。"""
        anchor = self._write(_memory("他今天加班到凌晨两点才回家",
                                     created="2026-10-20T09:00:00"))
        neighbour = self._write(_memory("楼下新开了一家面馆",
                                        created="2026-10-20T21:00:00"))
        query = "他今天加班到凌晨两点才回家"

        self.assertEqual(seeds(query, [neighbour]), [])
        self.assertEqual(seeds(query, [anchor, neighbour]), [anchor.header.id])
        activation = activate([anchor.header.id], self.graph, self.cache)
        self.assertGreater(activation.get(neighbour.header.id, 0.0), 0.0)


class BudgetTest(_LinkCase):
    """出度预算与幂等：单节点 ≤ MAX_EDGES，重复建边不增长。"""

    def test_out_degree_is_capped(self) -> None:
        """连续写入 8 条高度相似记忆：每个节点边数 ≤ 上限，且预算确实触顶。"""
        arts = [
            self._write(_memory("他今天又加班到很晚了",
                                created="2026-10-20T20:00:00"))
            for _ in range(8)
        ]
        degrees = [len(self._edges(art)) for art in arts]
        self.assertTrue(all(degree <= MAX_EDGES for degree in degrees), degrees)
        self.assertEqual(max(degrees), MAX_EDGES, degrees)

    def test_repeated_link_is_idempotent(self) -> None:
        """重复调用 link_new 不新增边；同一条边重复写入只更新权重。"""
        first = self._write(_memory("他今天加班到凌晨两点才回家",
                                    created="2026-10-18T20:00:00"))
        second = self._write(_memory("他今天加班到凌晨两点才回家，很累",
                                     created="2026-10-19T20:00:00"))
        before = self._edges(second)
        self.assertEqual(len(before), 1)

        self.assertEqual(link_new(second, self.graph, self.cache), 0)
        self.assertEqual(link_new(second, self.graph, self.cache), 0)
        self.assertEqual(self._edges(second), before)

        self.graph.link(second.header.id, first.header.id, "similar", 0.9)
        after = self._edges(second)
        self.assertEqual(len(after), 1)
        self.assertEqual(after[0], (first.header.id, "similar", 0.9))


class FailOpenTest(_LinkCase):
    """缺依赖或依赖抛异常时，建边失败但写入不受影响。"""

    def test_missing_graph_or_cache_returns_zero(self) -> None:
        """graph / cache 为 None（或图没有 db）时 link_new 返回 0。"""
        first = self._write(_memory("他今天加班到凌晨两点才回家",
                                    created="2026-10-18T20:00:00"))
        second = _memory("他今天加班到凌晨两点才回家，很累",
                         created="2026-10-19T20:00:00")

        self.assertEqual(link_new(second, None, self.cache), 0)
        self.assertEqual(link_new(second, self.graph, None), 0)
        self.assertEqual(link_new(second, Graph(None), self.cache), 0)
        self.assertEqual(persist(second, self.db.artifacts, None, None), 0)
        self.assertIsNotNone(self.db.artifacts.get(second.header.id))
        self.assertEqual(self._edges(first), [])
        self.assertEqual(self._edges(second), [])

    def test_cache_failure_does_not_block_write(self) -> None:
        """缓存索引抛异常时，记忆仍写库并进缓存，只是没有新边。"""
        first = self._write(_memory("他今天加班到凌晨两点才回家",
                                    created="2026-10-18T20:00:00"))
        second = _memory("他今天加班到凌晨两点才回家，很累",
                         created="2026-10-19T20:00:00")
        boom = _BoomCache(self.cache)

        persist(second, self.db.artifacts, boom, self.graph)  # type: ignore[arg-type]

        self.assertIsNotNone(self.db.artifacts.get(second.header.id))
        self.assertIsNotNone(self.cache.get(second.header.id))
        self.assertEqual(self._edges(first), [])
        self.assertEqual(self._edges(second), [])

    def test_graph_failure_does_not_block_write(self) -> None:
        """图写入失败时，persist 仍把记忆写库、入缓存，不向上抛异常。"""
        self._write(_memory("他今天加班到凌晨两点才回家",
                            created="2026-10-18T20:00:00"))
        second = _memory("他今天加班到凌晨两点才回家，很累",
                         created="2026-10-19T20:00:00")

        persist(second, self.db.artifacts, self.cache,  # type: ignore[arg-type]
                _BoomGraph(self.db.artifacts))

        self.assertIsNotNone(self.db.artifacts.get(second.header.id))
        self.assertIsNotNone(self.cache.get(second.header.id))
        self.assertEqual(self._edges(second), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
