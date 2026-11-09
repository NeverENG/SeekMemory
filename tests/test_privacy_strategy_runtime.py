"""Foreground and AgentRuntime context must use the same privacy strategy.

前台与 AgentRuntime 上下文必须使用同一隐私策略。
"""
from __future__ import annotations

import unittest

from adapters.astrbot.context import SeekMemoryContextAdapter
from app.budget import ContextBudget
from app.runtime import AgentRuntime, InMemoryStateStore
from app.runtime.contracts import MemoryContext, RuntimeInput
from core.domain.memory.artifact import Lineage, make
from core.domain.memory.disclosure import (
    DisclosureDecision, DisclosureLevel, PrivacyPolicy,
)
from core.domain.memory.graph import Graph
from core.domain.memory.source import Source
from services.recall_service import RecallService
from store import open_store
from store.cache import Cache


class WithholdPolicy(PrivacyPolicy):
    """Refuse ordinary selected memories at the injection boundary / 在注入边界拒绝普通已选记忆。"""

    def decide(self, art, scene, relevance, origins=()):
        return DisclosureDecision(DisclosureLevel.SILENCE, 0.0, "policy withheld")


class BrokenPolicy(PrivacyPolicy):
    """Fail a decision to prove protected content stays withheld / 通过决策失败验证受保护内容不会输出。"""

    def decide(self, art, scene, relevance, origins=()):
        raise RuntimeError("policy unavailable")


class BrokenPriorPolicy(PrivacyPolicy):
    """Reject all paths if the scope policy cannot run / 范围策略不可用时拒绝所有路径。"""

    def scope_prior(self, art):
        raise RuntimeError("scope policy unavailable")


class RestrictedPolicy(PrivacyPolicy):
    """A stricter scope prior must affect disclosure too / 收紧 scope 先验也必须影响披露。"""

    def scope_prior(self, art):
        return 0.0


class MaskPolicy(PrivacyPolicy):
    """Substitute a safe masked phrase / 替换安全的遮蔽措辞。"""

    def safe_text(self, art, level):
        return "已遮蔽"


class PrivacyStrategyRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.owner = "bot:FriendMessage:u1"
        self.text = "银河档案蓝铃"
        source = Source("source-policy", "turn-policy", self.owner, "u1", "user",
                        "source text", "2026-10-22T12:00:00")
        self.db.sources.append_sources([source])
        self.art = make(
            "memory", {"text": self.text, "level": "fact"},
            scope="private", subject_id="u1", said_by="u1",
            lineage=Lineage(sources=(source.id,)),
        )
        self.db.artifacts.commit(self.art, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(self.art)

    def service(self, policy: PrivacyPolicy | None = None) -> RecallService:
        return RecallService(
            cache=self.cache, graph=self.graph, artifacts=self.db.artifacts,
            sources=self.db.sources, budget=ContextBudget(injection_chars=600),
            config={"bm25_enabled": False, "explore_rate": 0.0,
                    "source_recall_enabled": False}.get,
            owner_umo=lambda: self.owner, privacy_policy=policy,
        )

    def contexts(self, service: RecallService, session: str) -> tuple[tuple[str, dict], MemoryContext]:
        direct = service.query(self.text, session, True, "u1")
        adapter = SeekMemoryContextAdapter(lambda request: MemoryContext(
            *service.query(request.query, request.session_id, request.private, request.speaker_id)
        ))
        runtime = AgentRuntime(InMemoryStateStore(), memory_context=adapter).build_context(RuntimeInput(
            session, self.text, speaker_id="u1", private=True,
        ), now=0.0, reason="deferred")
        return direct, runtime

    def test_default_same_session_full_and_cross_session_masked_on_both_paths(self) -> None:
        service = self.service()
        (same_text, same_info), same_runtime = self.contexts(service, self.owner)
        self.assertEqual(same_runtime.text, same_text)
        self.assertEqual(same_runtime.info["disclosure"], same_info["disclosure"])
        self.assertIn(self.text, same_text)
        self.assertEqual(same_info["disclosure"][self.art.header.id], "full")

        (cross_text, cross_info), cross_runtime = self.contexts(service, "bot:FriendMessage:else")
        self.assertEqual(cross_runtime.text, cross_text)
        self.assertEqual(cross_runtime.info["disclosure"], cross_info["disclosure"])
        self.assertNotIn(self.text, cross_text)
        self.assertIn(cross_info["disclosure"][self.art.header.id], ("paraphrase", "hint", "silence"))

    def test_injected_policy_withholds_on_both_paths_and_does_not_write(self) -> None:
        service = self.service(WithholdPolicy())
        before = self.db.artifacts.get(self.art.header.id).header.revision
        (text, info), runtime = self.contexts(service, self.owner)
        self.assertNotIn(self.text, text)
        self.assertNotIn(self.text, runtime.text)
        self.assertEqual(info["disclosure"][self.art.header.id], "silence")
        self.assertEqual(runtime.info["disclosure"], info["disclosure"])
        self.assertEqual(self.db.artifacts.get(self.art.header.id).header.revision, before)

    def test_stricter_prior_affects_disclosure_on_both_paths(self) -> None:
        (text, info), runtime = self.contexts(self.service(RestrictedPolicy()), self.owner)
        self.assertNotIn(self.text, text)
        self.assertNotIn(self.text, runtime.text)
        self.assertEqual(info["disclosure"][self.art.header.id], "silence")
        self.assertEqual(runtime.info["disclosure"], info["disclosure"])

    def test_safe_wording_uses_same_policy_on_both_paths(self) -> None:
        (text, info), runtime = self.contexts(self.service(MaskPolicy()), "bot:FriendMessage:else")
        self.assertNotIn(self.text, text)
        self.assertIn("已遮蔽", text)
        self.assertEqual(runtime.text, text)
        self.assertIn(info["disclosure"][self.art.header.id], ("paraphrase", "hint"))

    def test_broken_policy_fails_closed_on_both_paths(self) -> None:
        (text, info), runtime = self.contexts(self.service(BrokenPolicy()), self.owner)
        self.assertNotIn(self.text, text)
        self.assertNotIn(self.text, runtime.text)
        self.assertEqual(info["picked"], 0)
        self.assertEqual(runtime.info["picked"], 0)

    def test_broken_prior_cannot_leak_through_fallback(self) -> None:
        service = self.service(BrokenPriorPolicy())
        text, info = service.query("我的名字", self.owner, True, "u1")
        adapter = SeekMemoryContextAdapter(lambda request: MemoryContext(
            *service.query(request.query, request.session_id, request.private, request.speaker_id)
        ))
        runtime = AgentRuntime(InMemoryStateStore(), memory_context=adapter).build_context(
            RuntimeInput(self.owner, "我的名字", speaker_id="u1", private=True))
        self.assertEqual(info["fallback"], "recent_profile")
        self.assertNotIn(self.text, text)
        self.assertNotIn(self.text, runtime.text)
        self.assertEqual(info["final_ids"], ())
        self.assertEqual(runtime.info["final_ids"], ())

    def test_pinned_impression_uses_injected_policy_in_runtime(self) -> None:
        pinned_text = "蓝铃常驻印象"
        art = make(
            "memory", {"text": pinned_text, "level": "impression"},
            scope="private", subject_id="u1", said_by="owner",
            lineage=self.art.header.lineage,
        )
        self.db.artifacts.commit(art, expected_revision=0, op="create",
                                 source_ids=self.art.header.lineage.sources)
        self.cache.put(art)
        service = self.service(WithholdPolicy())
        direct, info = service.query("你好", self.owner, True, "u1")
        adapter = SeekMemoryContextAdapter(lambda request: MemoryContext(
            *service.query(request.query, request.session_id, request.private, request.speaker_id)
        ))
        runtime = AgentRuntime(InMemoryStateStore(), memory_context=adapter).build_context(
            RuntimeInput(self.owner, "你好", speaker_id="u1", private=True))
        self.assertNotIn(pinned_text, direct)
        self.assertNotIn(pinned_text, runtime.text)
        self.assertEqual(info["disclosure"][art.header.id], "silence")
        self.assertEqual(runtime.info["disclosure"][art.header.id], "silence")


if __name__ == "__main__":
    unittest.main()
