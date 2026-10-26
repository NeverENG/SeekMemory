"""Independent persona-lifecycle contract checks for issue #88.

Covers the matrix gaps the bootstrap/synthesis suites do not: one-call-per-cycle,
evidence privacy, no new Source rows, prompt hygiene, response size limits,
rollback validation/provenance/recall, CAS conflict and restart recovery.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from persona_support import PersonaCase
from app.persona_synthesis import (
    MAX_BOUNDARIES,
    MAX_BOUNDARY_CHARS,
    MAX_CHANGE_REASON,
    MAX_PERSONA_CHARS,
    build_persona_request,
    parse_persona_draft,
)
from core.artifact import Lineage, Strength, TimeSpan, make
from core.graph import Graph
from core.source import Source
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService
from services.recall_service import RecallService
from services.status_service import StatusService


class _Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        return None


class _FakeModel:
    def __init__(
        self, text: str = "", error: Exception | None = None, slow: bool = False
    ) -> None:
        self.text = text
        self.error = error
        self.slow = slow
        self.calls = 0
        self.request = None

    async def complete(self, request):
        self.calls += 1
        self.request = request
        if self.slow:
            # Yield so a second synthesis task can read the same base revision.
            await asyncio.sleep(0.02)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text, usage_in=1, usage_cached=0, usage_out=1)


def _seed() -> dict:
    return {
        "id": "contract_persona",
        "version": "1.0.0",
        "name": "契约人格",
        "persona": "你是契约测试人格。",
        "style": {"tone": "稳定"},
        "boundaries": ["不编造"],
    }


def _draft(day: int = 1, persona: str | None = None) -> str:
    return json.dumps(
        {
            "persona": persona or f"第 {day} 天的契约人格",
            "style": {"tone": "稳定"},
            "boundaries": ["不编造"],
            "change_reason": f"第 {day} 天更新",
        },
        ensure_ascii=False,
    )


class PersonaLifecycleContractTest(PersonaCase):
    def bootstrap(self) -> None:
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(_seed())

    def service(self, fake: _FakeModel, clock=None, **config) -> MaintenanceService:
        async def factory():
            return fake

        defaults = {
            "persona_synthesis_enabled": True,
            "persona_synthesis_interval_days": 0,
            "persona_synthesis_evidence_limit": 8,
            "persona_synthesis_evidence_chars": 2400,
        }
        defaults.update(config)
        return MaintenanceService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            cache=self.cache,
            journal=_Journal(),
            task_id=lambda: "task",
            logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            config=lambda key, default: defaults.get(key, default),
            persona_model=factory,
            clock=clock or datetime.datetime.now,
        )

    def add_memory(
        self,
        text: str,
        *,
        scope: str = "shared",
        shareable: str = "public",
        sources: tuple[str, ...] = ("s1",),
        level: str = "scene",
    ):
        now = datetime.datetime.now().isoformat(timespec="seconds")
        art = make(
            "memory",
            {"text": text, "level": level, "about": "other"},
            scope=scope,
            shareable=shareable,
            said_by="owner",
            strength=Strength(weight=2.0, confidence=1.0),
            lineage=Lineage(sources=sources),
            time=TimeSpan(created=now, updated=now),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=sources
        )
        self.cache.put(art)
        return art

    def add_source(self, source_id: str, text: str) -> None:
        self.db.sources.append_sources(
            [
                Source(
                    source_id,
                    source_id,
                    "session:1",
                    "person1",
                    "user",
                    text,
                    "2026-10-25T10:00:00",
                )
            ]
        )

    def source_rows(self) -> int:
        return int(
            self.db.sources.conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        )

    def recall(self):
        service = RecallService(
            cache=self.cache,
            graph=Graph(self.db.artifacts),
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            budget=SimpleNamespace(injection_chars=600),
            config={}.get,
            owner_umo=lambda: "",
        )
        return service.build("你好", private=True, speaker="owner", dry_run=True)

    # ---- synthesis -------------------------------------------------------

    def test_one_model_call_per_cycle_and_default_interval_skips(self) -> None:
        self.bootstrap()
        self.add_memory("最近在整理长期关系")
        skipped = _FakeModel(_draft())
        result = asyncio.run(
            self.service(skipped, persona_synthesis_interval_days=7).weekly()
        )
        self.assertEqual(result["persona_result"]["status"], "not_due")
        self.assertEqual(skipped.calls, 0)

        fake = _FakeModel(_draft())
        updated = asyncio.run(self.service(fake).weekly())
        self.assertEqual(updated["persona_result"]["status"], "updated")
        self.assertEqual(fake.calls, 1)
        self.assertEqual(self.cache.active("persona")[0].header.revision, 2)

    def test_private_and_secret_memories_never_reach_the_prompt(self) -> None:
        self.bootstrap()
        self.add_source("s_raw", "RAW_SOURCE_TEXT_不应出现")
        self.add_memory(
            "公开摘要 SHARED_OK", sources=("s_raw",), shareable="public"
        )
        self.add_memory("PRIVATE_ONLY", scope="private", shareable="private_only")
        self.add_memory("SECRET_SHARED", shareable="secret")

        fake = _FakeModel(_draft())
        result = asyncio.run(self.service(fake).weekly())
        self.assertEqual(result["persona_result"]["status"], "updated")
        prompt = fake.request.prompt
        self.assertIn("SHARED_OK", prompt)
        self.assertNotIn("PRIVATE_ONLY", prompt)
        self.assertNotIn("SECRET_SHARED", prompt)
        self.assertNotIn("RAW_SOURCE_TEXT", prompt)

    def test_only_private_evidence_produces_no_call_and_no_source(self) -> None:
        self.bootstrap()
        self.add_memory("PRIVATE_ONLY", scope="private", shareable="private_only")
        before = self.source_rows()
        fake = _FakeModel(_draft())
        result = asyncio.run(self.service(fake).weekly())
        self.assertEqual(result["persona_result"]["status"], "no_evidence")
        self.assertEqual(fake.calls, 0)
        self.assertEqual(self.source_rows(), before)

    def test_synthesis_creates_no_new_source_rows(self) -> None:
        self.bootstrap()
        self.add_source("s1", "公开来源正文")
        self.add_memory("公开摘要", sources=("s1",))
        before = self.source_rows()
        asyncio.run(self.service(_FakeModel(_draft())).weekly())
        self.assertEqual(self.source_rows(), before)

    def test_prompt_excludes_full_corpus_and_is_bounded(self) -> None:
        seed = _seed()
        seed["corpus"] = [
            {
                "user": (
                    f"第{i}段：CORPUS_USER_TEXT 今天发生了很多事情，我有点累，"
                    "想和你说说心里话，工作上的压力和生活中的琐事都挤在一起。"
                ),
                "assistant": (
                    f"第{i}次：CORPUS_ASSISTANT_TEXT 先缓一缓，我在听，"
                    "你可以慢慢讲，不想说也没关系，我会一直在这里等你。"
                ),
            }
            for i in range(12)
        ]
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(seed)
        self.add_memory("公开摘要")
        fake = _FakeModel(_draft())
        asyncio.run(self.service(fake).weekly())
        self.assertNotIn("CORPUS_USER_TEXT", fake.request.prompt)
        self.assertNotIn("CORPUS_ASSISTANT_TEXT", fake.request.prompt)
        self.assertLessEqual(len(fake.request.prompt), 2400 + 2000)

    def test_missing_provider_keeps_old_persona(self) -> None:
        self.bootstrap()
        self.add_memory("公开摘要")

        async def no_provider():
            return None

        service = MaintenanceService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            cache=self.cache,
            journal=_Journal(),
            task_id=lambda: "task",
            logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            config=lambda key, default: {
                "persona_synthesis_enabled": True,
                "persona_synthesis_interval_days": 0,
                "persona_synthesis_evidence_limit": 8,
                "persona_synthesis_evidence_chars": 2400,
            }.get(key, default),
            persona_model=no_provider,
            clock=datetime.datetime.now,
        )
        result = asyncio.run(service.weekly())
        self.assertEqual(result["persona_result"]["status"], "failed")
        active = self.cache.active("persona")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].header.revision, 1)

    # ---- prompt/response validation --------------------------------------

    def test_parser_rejects_oversized_or_incomplete_fields(self) -> None:
        current = {"text": "旧人格"}
        too_long_persona = json.dumps(
            {
                "persona": "长" * (MAX_PERSONA_CHARS + 1),
                "style": {},
                "boundaries": [],
                "change_reason": "x",
            },
            ensure_ascii=False,
        )
        too_many_boundaries = json.dumps(
            {
                "persona": "新人格",
                "style": {},
                "boundaries": ["边界"] * (MAX_BOUNDARIES + 1),
                "change_reason": "x",
            },
            ensure_ascii=False,
        )
        long_boundary = json.dumps(
            {
                "persona": "新人格",
                "style": {},
                "boundaries": ["边" * (MAX_BOUNDARY_CHARS + 1)],
                "change_reason": "x",
            },
            ensure_ascii=False,
        )
        long_reason = json.dumps(
            {
                "persona": "新人格",
                "style": {},
                "boundaries": [],
                "change_reason": "理" * (MAX_CHANGE_REASON + 1),
            },
            ensure_ascii=False,
        )
        missing_reason = json.dumps(
            {"persona": "新人格", "style": {}, "boundaries": []},
            ensure_ascii=False,
        )
        for raw in (
            too_long_persona,
            too_many_boundaries,
            long_boundary,
            long_reason,
            missing_reason,
        ):
            with self.subTest(raw=raw[:40]):
                with self.assertRaises(ValueError):
                    parse_persona_draft(raw, current)

    def test_request_builder_keeps_evidence_bounded(self) -> None:
        request = build_persona_request(
            {"text": "旧人格", "corpus": [{"user": "CORPUS"}]},
            [],
            max_evidence_chars=200,
        )
        self.assertNotIn("CORPUS", request.prompt)
        self.assertTrue(request.json_mode)
        self.assertEqual(request.session_id, "dream:persona")

    # ---- rollback --------------------------------------------------------

    def test_rollback_validation_matrix(self) -> None:
        self.bootstrap()
        manager = ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )
        persona_id = self.cache.active("persona")[0].header.id
        memory = self.add_memory("普通记忆")
        cases = [
            ({"id": memory.header.id, "revision": 1, "reason": "x", "confirmed": True},
             ValueError),
            ({"id": "missing", "revision": 1, "reason": "x", "confirmed": True},
             LookupError),
            ({"id": persona_id, "revision": 9, "reason": "x", "confirmed": True},
             ValueError),
            ({"id": persona_id, "revision": 1, "reason": "x", "confirmed": False},
             ValueError),
            ({"id": persona_id, "revision": 1, "reason": "", "confirmed": True},
             ValueError),
            ({"id": persona_id, "revision": 1, "reason": "x"},
             ValueError),
            ({"id": persona_id, "revision": 1, "reason": "x", "confirmed": True,
              "extra": 1}, ValueError),
        ]
        for body, error in cases:
            with self.subTest(body=body):
                with self.assertRaises(error):
                    manager.rollback_persona(body)
        self.assertEqual(self.cache.active("persona")[0].header.revision, 1)

    def test_rollback_current_revision_is_rejected(self) -> None:
        self.bootstrap()
        self.add_memory("公开摘要")
        asyncio.run(self.service(_FakeModel(_draft())).weekly())
        manager = ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )
        persona = self.cache.active("persona")[0]
        with self.assertRaises(ValueError):
            manager.rollback_persona(
                {"id": persona.header.id, "revision": persona.header.revision,
                 "reason": "当前版本", "confirmed": True}
            )

    def test_rollback_to_seed_restores_a_trusted_seed_payload(self) -> None:
        """Documented behavior: seed rollback restores corpus to stay trusted.

        ``trusted_self_persona`` accepts a seed payload only when corpus is
        absent with zero count/hash, or present with matching count/hash. A
        corpus-less seed revision is therefore not trusted today; issue #88's
        "corpus only on the initial revision" checkpoint is asserted for
        synthesized revisions, and this test pins the seed-rollback trade-off.
        """
        seed = _seed()
        seed["corpus"] = [
            {
                "user": (
                    f"第{i}段：今天发生了很多事情，我有点累，想和你说说心里话，"
                    "工作上的压力和生活中的琐事都挤在一起，想找个地方安静一会儿。"
                ),
                "assistant": (
                    f"第{i}次：先缓一缓，我在听，你可以慢慢讲，"
                    "不想说也没关系，我会一直在这里等你，不用一个人扛着。"
                ),
            }
            for i in range(12)
        ]
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(seed)
        initial = self.cache.active("persona")[0]
        persona_id = initial.header.id
        persona_hash = initial.payload["corpus_hash"]
        # A second install creates revision 2 so revision 1 is historical.
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(seed)

        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).rollback_persona(
            {"id": persona_id, "revision": 1, "reason": "回到种子", "confirmed": True}
        )
        restored = self.cache.active("persona")[0]
        self.assertEqual(restored.header.revision, 3)
        self.assertEqual(restored.payload["origin"], "seed")
        self.assertEqual(restored.payload["corpus_count"], 12)
        self.assertEqual(restored.payload["corpus_hash"], persona_hash)
        self.assertEqual(len(restored.payload["corpus"]), 12)
        self.assertTrue(self.trusted(restored))

    @staticmethod
    def trusted(art) -> bool:
        from core.bot_behavior import trusted_self_persona

        return trusted_self_persona(art)

    def test_rollback_provenance_and_recall_follow_the_restored_revision(self) -> None:
        self.bootstrap()
        self.add_memory("公开摘要")
        asyncio.run(self.service(_FakeModel(_draft(1))).weekly())
        persona_id = self.cache.active("persona")[0].header.id
        manager = ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )

        manager.rollback_persona(
            {"id": persona_id, "revision": 1, "reason": "回到种子", "confirmed": True}
        )
        seed = self.cache.active("persona")[0]
        self.assertEqual(seed.payload["text"], "你是契约测试人格。")
        timeline = StatusService(artifacts=self.db.artifacts,
                                 ledger=self.db.ledger).persona()
        assert timeline is not None
        self.assertEqual(timeline["origin"], "seed")
        self.assertEqual(timeline["revisions"][-1]["origin"], "seed")
        self.assertEqual([row["revision"] for row in timeline["revisions"]], [1, 2, 3])
        block, info = self.recall()
        self.assertIn("你是契约测试人格。", block)
        self.assertIn(seed.header.id, info["final_ids"])
        self.assertNotIn("第 1 天的契约人格", block)

        manager.rollback_persona(
            {"id": persona_id, "revision": 2, "reason": "恢复合成版", "confirmed": True}
        )
        block, info = self.recall()
        self.assertIn("第 1 天的契约人格", block)
        self.assertIn(persona_id, info["final_ids"])

    # ---- concurrency / recovery ------------------------------------------

    def test_concurrent_synthesis_commits_exactly_once(self) -> None:
        self.bootstrap()
        self.add_memory("公开摘要")
        first = self.service(_FakeModel(_draft(1), slow=True))
        second = self.service(_FakeModel(_draft(2), slow=True))

        async def run():
            return await asyncio.gather(
                first._synthesize_persona_async(),
                second._synthesize_persona_async(),
            )

        results = asyncio.run(run())
        statuses = sorted(result["status"] for result in results)
        self.assertEqual(statuses, ["failed", "updated"])
        active = self.cache.active("persona")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].header.revision, 2)
        self.assertEqual(len(self.db.artifacts.history(active[0].header.id)), 2)
        self.assertEqual(
            [art.header.id for art in self.cache.active("persona")],
            [active[0].header.id],
        )

    def test_restart_preserves_persona_history_and_active_selection(self) -> None:
        self.bootstrap()
        self.add_memory("公开摘要")
        asyncio.run(self.service(_FakeModel(_draft())).weekly())
        persona_id = self.cache.active("persona")[0].header.id
        path = self.db.path

        self.db.close()
        from store import open_store
        from store.cache import Cache

        self.db = open_store(path)
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.cache.load()

        active = self.cache.active("persona")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].header.id, persona_id)
        self.assertEqual(active[0].header.revision, 2)
        self.assertEqual(active[0].payload["origin"], "dream")
        self.assertEqual(len(self.db.artifacts.history(persona_id)), 2)


if __name__ == "__main__":
    unittest.main()
