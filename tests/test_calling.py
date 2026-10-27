"""调用方式与印象修订的测试：什么时候翻记忆、会不会想起、印象会不会变。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Strength, content_of, make  # noqa: E402
from maintain.impression import revise_impression  # noqa: E402
from recall.drift import best_of, eligible, should_drift  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.gate import pinned  # noqa: E402
from recall.history import trajectory  # noqa: E402
from perceive.calls import log_call  # noqa: E402
from recall.intent import intent_of  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402


def temp_cache():
    """建临时库并返回 (db, cache)。"""
    path = os.path.join(tempfile.mkdtemp(prefix="seekmem_call_"), "t.db")
    db = open_store(path)
    return db, Cache(db.artifacts)


def mem(text, level="scene", weight=1.5, scope="private", arousal=0.4):
    """快速造一条 memory。"""
    return make("memory", {"text": text, "level": level, "tags": "tag"},
                strength=Strength(weight=weight, arousal=arousal), scope=scope)


class IntentTest(unittest.TestCase):
    def test_chitchat_is_none(self):
        for text in ("在吗", "早", "晚安", "吃了吗", "嗯", "哈哈"):
            self.assertEqual(intent_of(text), "none", text)

    def test_clock_is_none(self):
        for text in ("今天几号", "现在几点", "今天星期几"):
            self.assertEqual(intent_of(text), "none", text)

    def test_operation_is_none(self):
        self.assertEqual(intent_of("帮我写个匹配手机号的正则"), "none")

    def test_recall_question_is_loose(self):
        for text in ("你还记得我叫什么吗", "上次那家公司怎么样", "你最了解我什么"):
            self.assertEqual(intent_of(text), "loose", text)

    def test_mood_is_loose(self):
        self.assertEqual(intent_of("我今天好累"), "loose")

    def test_normal_statement_is_strict(self):
        self.assertEqual(intent_of("今天下午三点开会"), "strict")

    def test_duration_question_is_recall(self):
        # 「上次加班到几点」是回忆题，不是问时间
        self.assertEqual(intent_of("我上次加班到几点"), "loose")


class DriftTest(unittest.TestCase):
    def test_eligible_filters(self):
        self.assertTrue(eligible(mem("他养了只猫")))
        self.assertFalse(eligible(mem("别人秘密", scope="shadow")))
        self.assertFalse(eligible(mem("一句话", level="persona")))

    def test_best_of_prefers_heavy_and_recent(self):
        light = mem("最近提过的小事", weight=0.8)
        heavy = mem("他面试过了", weight=2.4, arousal=0.9)
        self.assertIs(best_of([light, heavy], seed=1), heavy)

    def test_best_of_empty(self):
        self.assertIsNone(best_of([], seed=1))

    def test_should_drift_short_only(self):
        self.assertFalse(should_drift("这是一句很长的关于项目进度的说明，不该主动想起什么", seed=1))
        hits = sum(1 for i in range(200) if should_drift("嗯", seed=i))
        self.assertTrue(0 < hits < 80)  # 有概率，但不是必然


class ImpressionTest(unittest.TestCase):
    def test_same_impression_reinforced(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression", weight=1.5)
        db.artifacts.upsert(old)
        cache.put(old)
        new = mem("他有点倔，嘴上不饶人", level="impression", weight=1.6)
        db.artifacts.commit(new, expected_revision=0, op="create")
        cache.put(new)
        got = revise_impression(db.artifacts, cache, new)
        self.assertIsNotNone(got)
        self.assertEqual(got.header.id, old.header.id)
        self.assertEqual(got.header.revision, old.header.revision + 1)
        self.assertGreater(got.header.strength.weight, 1.6)
        self.assertEqual(got.header.strength.hits, 1)

    def test_reworded_impression_new_revision(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression", weight=1.5)
        db.artifacts.upsert(old)
        cache.put(old)
        new = mem("他有点倔，嘴上不饶人，但真有事会帮", level="impression", weight=1.6)
        db.artifacts.commit(new, expected_revision=0, op="create")
        cache.put(new)
        got = revise_impression(db.artifacts, cache, new)
        self.assertIsNotNone(got)
        self.assertEqual(got.header.revision, old.header.revision + 1)
        self.assertIn("真有事会帮", content_of(got))
        self.assertIn(new.header.id, got.header.lineage.derived_from)
        self.assertNotIn(got.header.id, got.header.lineage.derived_from)

    def test_unrelated_impression_untouched(self):
        db, cache = temp_cache()
        old = mem("他有点倔，嘴上不饶人", level="impression")
        db.artifacts.upsert(old)
        cache.put(old)
        got = revise_impression(db.artifacts, cache, mem("他很会做饭，做得不错", level="impression"))
        self.assertIsNone(got)

    def test_non_impression_ignored(self):
        db, cache = temp_cache()
        self.assertIsNone(revise_impression(db.artifacts, cache, mem("他面试过了", level="scene")))


class LayerOrderTest(unittest.TestCase):
    """人格 > 印象 > 场景 > 细节 > 事实。"""

    def _arts(self):
        p = make("persona", {"text": "你是大肥鱼"},
                 strength=Strength(weight=2.0), said_by="inferred")
        imp = mem("他有点倔", level="impression", weight=2.0)
        scene = mem("他面试过了", level="scene", weight=1.8)
        detail = mem("加班到两点", level="detail", weight=1.5)
        fact = mem("他在杭州", level="fact", weight=1.2)
        return p, imp, scene, detail, fact

    def test_order(self):
        block = assemble(list(self._arts()), budget=2000)
        idx = [block.find(t) for t in ("大肥鱼", "有点倔", "面试过了", "加班到两点", "杭州")]
        self.assertTrue(all(i >= 0 for i in idx), block)
        self.assertEqual(idx, sorted(idx), block)

    def test_facts_dropped_before_scenes(self):
        block = assemble(list(self._arts()), budget=34)
        self.assertIn("大肥鱼", block)
        self.assertNotIn("杭州", block)  # 事实最先被砍

    def test_two_impressions_kept(self):
        imp2 = mem("他心软", level="impression", weight=1.9)
        block = assemble([self._arts()[0], self._arts()[1], imp2], budget=2000)
        self.assertIn("有点倔", block)
        self.assertIn("心软", block)


class PinnedSubjectTest(unittest.TestCase):
    """印象分人：跟谁说话就调出对谁的印象。"""

    def _cache(self):
        db, cache = temp_cache()
        for art in (make("memory", {"text": "他有点倔", "level": "impression"},
                         strength=Strength(weight=2.0), said_by="owner"),
                    make("memory", {"text": "12345 爱开玩笑", "level": "impression"},
                         strength=Strength(weight=2.0), said_by="12345")):
            db.artifacts.upsert(art)
            cache.put(art)
        return cache

    def test_owner_gets_owner_impression(self):
        got = [str(a.payload.get("text")) for a in pinned(self._cache(), "owner")]
        self.assertIn("他有点倔", got)
        self.assertNotIn("12345 爱开玩笑", got)

    def test_other_person_gets_his_own(self):
        got = [str(a.payload.get("text")) for a in pinned(self._cache(), "12345")]
        self.assertIn("12345 爱开玩笑", got)
        self.assertNotIn("他有点倔", got)


class TrajectoryTest(unittest.TestCase):
    """版本链：同一印象改过之后，能说清以前怎么想、现在怎么想。"""

    def _cache(self):
        db, cache = temp_cache()
        old = mem("他有点倔", level="impression", weight=1.6)
        db.artifacts.upsert(old)
        cache.put(old)
        self.assertEqual(trajectory(cache, old), "")  # 只有一版没有轨迹
        new = mem("他有点倔，但真有事会帮", level="impression", weight=1.8)
        db.artifacts.commit(new, expected_revision=0, op="create")
        cache.put(new)
        got = revise_impression(db.artifacts, cache, new)
        self.assertIsNotNone(got)
        return cache, got

    def test_trajectory_text(self):
        cache, art = self._cache()
        note = trajectory(cache, art)
        self.assertIn("觉得", note)
        self.assertIn("有点倔", note)

    def test_history_keeps_both_revisions(self):
        cache, art = self._cache()
        rows = cache.artifacts.history(art.header.id)
        self.assertEqual([r["revision"] for r in rows], [1, 2])
        self.assertIn("有点倔", rows[0]["payload"]["text"])
        self.assertIn("真有事", rows[1]["payload"]["text"])

    def test_note_rendered_after_impression(self):
        cache, art = self._cache()
        note = trajectory(cache, art)
        block = assemble([art], budget=500, notes={art.header.id: note})
        self.assertIn("觉得", block)


class CallLogTest(unittest.TestCase):
    """调用日志：记的是"这轮翻没翻记忆"，不记内容。"""

    def test_log_and_read(self):
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_call_"), "calls.jsonl")
        log_call(path, "napcat:GroupMessage:1", {"mode": "none", "picked": 0, "chars": 0})
        log_call(path, "napcat:FriendMessage:2", {"mode": "loose", "picked": 3, "chars": 41})
        rows = [json.loads(line) for line in open(path, encoding="utf-8")]
        self.assertEqual([r["mode"] for r in rows], ["none", "loose"])
        self.assertEqual(rows[1]["picked"], 3)
        self.assertEqual(rows[0]["kind"], "GroupMessage")

    def test_bad_path_is_silent(self):
        log_call("", "x", {})  # 不抛异常就算过


if __name__ == "__main__":
    unittest.main()
