from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Lineage, make
from core.graph import Graph
from core.source import Source
from recall.pipeline import build_block
from recall.retriever import HybridRetriever
from store.cache import Cache
from store.db import DB
from webui.service import ManagementService


class PipelineDisclosureTest(unittest.TestCase):
    def test_cross_session_shared_memory_is_paraphrased(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db)
        graph = Graph(db, cache)
        src = Source("s1", "turn1", "s1", "u1", "user", "source text", "t")
        db.append_sources([src])
        art = make("memory", {"text": "top secret phrase", "level": "scene",
                              "tags": "project"}, subject_id="u1", scope="shared")
        db.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        cache.put(art)
        config = {"bm25_enabled": True}
        block, info = build_block(
            cache, graph, db, "s2", "top secret phrase", True,
            lambda key, default: config.get(key, default),
            "napcat:FriendMessage:u1", "u1",
            hybrid_retriever=HybridRetriever(graph, cache),
        )
        self.assertTrue(block)
        self.assertNotIn("top secret phrase", block)
        self.assertEqual(info["disclosure"][art.header.id], "paraphrase")

    def test_bm25_does_not_make_private_memory_visible_cross_session(self):
        db = DB(os.path.join(tempfile.mkdtemp(), "t.db"))
        cache = Cache(db)
        graph = Graph(db, cache)
        source = Source("s1", "turn1", "s1", "u1", "user", "private source", "t")
        db.append_sources([source])
        art = make(
            "memory", {"text": "唯一的量化交易私密短语", "level": "scene"},
            scope="private", subject_id="u1",
        )
        db.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        cache.put(art)
        config = {"bm25_enabled": True}

        block, info = build_block(
            cache, graph, db, "s2", "还记得唯一的量化交易私密短语吗", True,
            lambda key, default: config.get(key, default),
            "napcat:FriendMessage:u1", "u2",
            hybrid_retriever=HybridRetriever(graph, cache),
        )

        self.assertNotIn("唯一的量化交易私密短语", block)
        self.assertEqual(info["picked_ids"], ())


class OptionalBM25PipelineTest(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)
        self.graph = Graph(self.db, self.cache)
        self.session = "bot:FriendMessage:u1"
        self.conf = {"bm25_enabled": True, "owner_umo": self.session,
                     "explore_rate": 0.0}
        self.retriever = HybridRetriever(self.graph, self.cache)

    def save(self, family, payload, scope="private"):
        number = self.cache.size()
        source = Source(f"s{number}", f"turn{number}", self.session, "u1", "user",
                        "synthetic fixture", "2026-10-22T12:00:00")
        self.db.append_sources([source])
        art = make(family, {**payload, "owner_umo": self.session}, scope=scope,
                   subject_id="u1", lineage=Lineage(sources=(source.id,)))
        self.db.commit(art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(art)
        return art

    def recall(self, query, config=None, injected=None):
        return build_block(
            self.cache, self.graph, self.db, self.session, query, True,
            (config or self.conf).get, self.session, "u1", dry_run=True,
            hybrid_retriever=injected or self.retriever,
        )

    def save_tagged_case(self):
        from benchmarks.bm25_holdout import HOLDOUT_CASES

        case = next(case for case in HOLDOUT_CASES if case.id == "tagged_spare_item")
        for doc in case.distractors:
            self.save("memory", {"text": doc.text, "tags": list(doc.tags), "level": "fact"})
        target = self.save("memory", {"text": case.target.text,
                                     "tags": list(case.target.tags), "level": "fact"})
        # loose 模式会加 2，对齐离线独立验收的有效 top-8。
        self.conf["recall_k"] = 6
        return case.query, target

    def test_disabled_bm25_keeps_legacy_selection(self):
        query, target = self.save_tagged_case()
        disabled = {**self.conf, "bm25_enabled": False}
        block, info = self.recall(query, disabled)
        self.assertNotIn(target.header.id, info["picked_ids"])
        self.assertNotIn("第二格抽屉", block)

    def test_default_bm25_recovers_tagged_memory_through_real_pipeline(self):
        query, target = self.save_tagged_case()
        schema_path = Path(__file__).resolve().parents[1] / "_conf_schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        defaults = {**self.conf, "bm25_enabled": schema["bm25_enabled"]["default"]}
        absent = {key: value for key, value in self.conf.items() if key != "bm25_enabled"}
        for config in (defaults, absent):
            with self.subTest(config=config):
                block, info = self.recall(query, config)
                self.assertIn(target.header.id, info["picked_ids"])
                self.assertIn("第二格抽屉", block)

    def test_disabled_bm25_ignores_invalid_lexical_weight(self):
        target = self.save("memory", {"text": "最近在复习量化交易", "level": "fact"})
        for weight in (float("nan"), float("inf"), "invalid", None):
            config = {**self.conf, "bm25_enabled": False, "bm25_weight": weight}
            with self.subTest(weight=weight):
                block, info = self.recall("还记得量化交易吗", config)
                self.assertIn(target.header.id, info["picked_ids"])
                self.assertIn("最近在复习量化交易", block)

    def test_shadow_and_secret_never_inject_bodies_with_bm25(self):
        self.save("memory", {"text": "影子中不能公开的量化密码", "level": "fact"}, "shadow")
        self.save("secret", {"ref": "secret-reference", "shadow_text": "量化私密承诺"})
        block, info = self.recall("还记得量化密码和私密承诺吗")
        self.assertNotIn("影子中不能公开的量化密码", block)
        self.assertNotIn("secret-reference", block)
        self.assertNotIn("量化私密承诺", block)
        self.assertNotIn("full", info["disclosure"].values())

    def test_readonly_diagnosis_does_not_consume_designated_delivery(self):
        designated = self.save("designated", {"text": "归还书籍清单", "trigger": "书籍"})
        service = ManagementService(self.db, self.cache, self.graph, self.conf.get,
                                    self.retriever)
        result = service.diagnose({"query": "还记得书籍吗", "umo": self.session,
                                   "speaker": "u1"})
        self.assertIn("归还书籍清单", result["block"])
        self.assertEqual(self.db.get(designated.header.id), designated)

    def test_clock_question_does_not_retrieve_bm25_matches(self):
        self.save("memory", {"text": "今天几号的问题", "level": "fact"})
        block, info = self.recall("今天几号")
        self.assertEqual(info["picked_ids"], ())
        self.assertEqual(block, "")

    def test_enabled_bm25_recovers_tagged_memory_through_real_pipeline(self):
        query, target = self.save_tagged_case()
        block, new_info = self.recall(query)
        self.assertIn(target.header.id, new_info["picked_ids"])
        self.assertIn("第二格抽屉", block)


if __name__ == "__main__":
    unittest.main()
