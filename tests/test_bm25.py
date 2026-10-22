from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make, revise
from core.graph import Graph
from core.retrieval import RetrievalCandidate
from recall.bm25 import BM25Index
from recall.retriever import GraphRetriever, HybridRetriever
from recall.score import select
from recall.tokenizer import tokenize
from store.cache import Cache
from store.db import DB


class TokenizerTest(unittest.TestCase):
    def test_character_bigrams_keep_repeated_terms(self):
        self.assertEqual(tokenize("A-A-A"), ["aa", "aa"])

    def test_empty_and_punctuation_have_no_terms(self):
        self.assertEqual(tokenize(""), [])
        self.assertEqual(tokenize("，。！？"), [])

    def test_single_character_is_kept(self):
        self.assertEqual(tokenize("甲"), ["甲"])


def memory(text: str, tags: list[str] | None = None) -> Artifact:
    payload = {"text": text, "level": "fact", "shape": "pattern",
               "chrono": "once", "about": "other"}
    if tags is not None:
        payload["tags"] = tags
    return make("memory", payload)


class BM25IndexTest(unittest.TestCase):
    def test_search_prefers_rare_and_repeated_terms(self):
        rare = memory("量化交易量化")
        common = memory("量化项目")
        noise = memory("今天开会")
        index = BM25Index(calibration_c=1.0)
        index.rebuild([rare, common, noise])

        scores = index.search("量化", [rare, common, noise])

        self.assertGreater(scores[rare.header.id], scores[common.header.id])
        self.assertNotIn(noise.header.id, scores)

    def test_text_and_tag_fields_are_combined_in_range(self):
        tagged = memory("普通内容", ["量化交易"])
        body = memory("量化交易项目")
        index = BM25Index(calibration_c=2.0)
        index.rebuild([tagged, body])

        scores = index.search("量化交易", [tagged, body])

        self.assertEqual(set(scores), {tagged.header.id, body.header.id})
        self.assertTrue(all(0.0 < value < 1.0 for value in scores.values()))

    def test_identical_field_evidence_weights_text_three_times_as_much(self):
        body = memory("量化")
        tagged = memory("", ["量化"])
        index = BM25Index(calibration_c=2.0)
        index.rebuild([body, tagged])
        scores = index.search("量化", [body, tagged])
        self.assertAlmostEqual(scores[body.header.id], scores[tagged.header.id] * 3)

    def test_tags_do_not_create_terms_between_separate_labels(self):
        art = memory("", ["量化", "交易"])
        index = BM25Index()
        index.put(art)
        self.assertEqual(index.search("化交", [art]), {})

    def test_nonfinite_calibration_is_rejected(self):
        for value in (0.0, -1.0, float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                BM25Index(value)

    def test_empty_and_single_character_queries(self):
        one = memory("甲")
        index = BM25Index()
        index.rebuild([one])

        self.assertEqual(index.search("，。", [one]), {})
        self.assertGreater(index.search("甲", [one])[one.header.id], 0.0)

    def test_allowed_pool_controls_corpus_statistics(self):
        target = memory("量化交易项目")
        excluded = memory("量化交易记录" * 20)
        all_indexed = BM25Index(calibration_c=2.0)
        all_indexed.rebuild([target, excluded])
        only_target_indexed = BM25Index(calibration_c=2.0)
        only_target_indexed.rebuild([target])

        restricted = all_indexed.search("量化交易", [target])
        isolated = only_target_indexed.search("量化交易", [target])

        self.assertEqual(restricted, isolated)

    def test_updates_and_removals_change_search_results(self):
        original = memory("量化交易项目")
        replacement = revise(original, payload=memory("数据库迁移").payload)
        index = BM25Index()
        index.rebuild([original])
        self.assertTrue(index.search("量化交易", [original]))

        index.put(replacement)
        self.assertEqual(index.search("量化交易", [replacement]), {})
        self.assertTrue(index.search("数据库", [replacement]))

        index.remove(replacement.header.id)
        self.assertEqual(index.search("数据库", [replacement]), {})

    def test_rebuild_discards_old_terms_and_nonactive_documents(self):
        old = memory("旧的量化工作")
        active = memory("新的数据库工作")
        forgotten = revise(old, state="forgotten")
        index = BM25Index()
        index.put(old)
        index.rebuild([active, forgotten])
        self.assertEqual(index.search("量化", [old, active]), {})
        self.assertIn(active.header.id, index.search("数据库", [old, active]))


class CacheVersionTest(unittest.TestCase):
    def test_cache_version_changes_when_active_documents_change(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db)
        art = memory("量化交易项目")
        initial = cache.version

        cache.put(art)
        after_put = cache.version
        cache.remove(art.header.id)

        self.assertGreater(after_put, initial)
        self.assertGreater(cache.version, after_put)

    def test_reloading_empty_cache_advances_version(self):
        db = DB(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db)
        initial = cache.version
        cache.load()
        self.assertGreater(cache.version, initial)


class RetrieverTest(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)
        self.graph = Graph(self.db, self.cache)

    def test_hybrid_retriever_adds_lexical_signal_once_per_artifact(self):
        relevant = memory("量化交易项目")
        unrelated = memory("周末去爬山")
        cache = self.cache
        cache.put(relevant)
        cache.put(unrelated)
        retriever = HybridRetriever(self.graph, cache)

        candidates = retriever.retrieve("量化交易", [relevant, unrelated, relevant])

        by_id = {candidate.artifact.header.id: candidate for candidate in candidates}
        self.assertEqual(len(candidates), 2)
        self.assertEqual(len(by_id), 2)
        self.assertGreater(by_id[relevant.header.id].lexical, 0.0)
        self.assertEqual(by_id[unrelated.header.id].lexical, 0.0)

    def test_graph_activation_survives_lexical_merge(self):
        seed = memory("量化交易项目")
        linked = memory("相关的另一个事件")
        pool = [seed, linked]
        for art in pool:
            self.cache.put(art)
        self.graph.link(seed.header.id, linked.header.id, "similar", 0.8)
        baseline = GraphRetriever(self.graph, self.cache).retrieve("量化交易", pool)
        hybrid = HybridRetriever(self.graph, self.cache).retrieve("量化交易", pool)
        self.assertEqual([a.activation for a in baseline], [a.activation for a in hybrid])
        self.assertGreater(hybrid[1].activation, 0)

    def test_retriever_tracks_revision_forget_restore_and_merge(self):
        art = memory("量化交易项目")
        self.cache.put(art)
        retriever = HybridRetriever(self.graph, self.cache)
        self.assertGreater(retriever.retrieve("量化交易", [art])[0].lexical, 0)
        updated = revise(art, payload={**art.payload, "text": "数据库迁移"})
        self.cache.put(updated)
        self.assertEqual(retriever.retrieve("量化交易", [updated])[0].lexical, 0)
        for state in ("forgotten", "active", "merged"):
            updated = revise(updated, state=state)
            self.cache.put(updated)
            found = retriever.retrieve("数据库", self.cache.active())
            self.assertEqual(bool(found), state == "active")
            if found:
                self.assertGreater(found[0].lexical, 0)

    def test_select_uses_configured_lexical_weight(self):
        text_match = memory("量化")
        bm25_match = memory("另一条完全不同的记忆")
        candidates = [
            (text_match, 0.0),
            RetrievalCandidate(bm25_match, lexical=1.0),
        ]
        default = select(candidates, "量化交易", 0.0, k=2, explore=0.0,
                         gate=False)
        weighted = select(candidates, "量化交易", 0.0, k=2, explore=0.0,
                          gate=False, lexical_weight=0.5)

        self.assertEqual(default[0].header.id, bm25_match.header.id)
        self.assertEqual(weighted[0].header.id, text_match.header.id)

    def test_nonfinite_weight_cannot_poison_the_evidence_gate(self):
        candidate = RetrievalCandidate(memory("量化"), lexical=0.5)
        for value in (float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                select([candidate], "量化", 0.0, lexical_weight=value)


if __name__ == "__main__":
    unittest.main()
