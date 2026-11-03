"""Dream persona synthesis: prompt, validation and same-lineage write."""
from __future__ import annotations

import datetime
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from persona_support import PersonaCase
from app.persona_synthesis import (
    PersonaEvidence,
    build_persona_request,
    parse_persona_draft,
)
from core.artifact import Lineage, Strength, TimeSpan, make
from core.bot_behavior import trusted_self_persona
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService
from services.status_service import StatusService


class _Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        return None


def _corpus() -> list[dict[str, str]]:
    return [
        {
            "user": (
                f"第{i}个场景：我今天有点累，想和你说说心里话。"
                "工作上的压力和生活中的琐事都挤在一起，我现在只想安静一会儿。"
            ),
            "assistant": (
                f"先缓一缓，我在听。第{i}次也会陪着你，不用一个人扛着。"
                "你可以慢慢讲，不想说也没关系，我会在这里等你。"
            ),
        }
        for i in range(12)
    ]


def _direct_seed(with_corpus: bool = False) -> dict:
    data = {
        "id": "big_fish",
        "version": "1.0.0",
        "name": "大肥鱼",
        "persona": "你是大肥鱼，温柔但嘴硬。",
        "style": {"tone": "温柔嘴硬"},
        "boundaries": ["不伪造用户经历"],
        "license": "CC0-1.0",
    }
    if with_corpus:
        data["corpus"] = _corpus()
    return data


def _config(values: dict):
    return lambda key, default: values.get(key, default)


class _FakeModel:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.request = None

    async def complete(self, request):
        self.request = request
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            text=self.text, usage_in=11, usage_cached=2, usage_out=7
        )


class PersonaSynthesisPureTest(unittest.TestCase):
    def test_request_is_bounded_and_excludes_corpus(self) -> None:
        current = {
            "text": "旧人格",
            "style": {"tone": "温柔"},
            "boundaries": ["不编造"],
            "corpus": [{"user": "SECRET_CORPUS", "assistant": "SECRET_CORPUS"}],
        }
        evidence = [
            PersonaEvidence("n1", "self_impression", "他喜欢被温柔回应" * 100)
        ]
        request = build_persona_request(current, evidence, max_evidence_chars=120)
        self.assertNotIn("SECRET_CORPUS", request.prompt)
        self.assertIn("旧人格", request.prompt)
        self.assertEqual(request.session_id, "dream:persona")
        self.assertTrue(request.json_mode)

    def test_parse_accepts_fenced_json_and_rejects_same_text(self) -> None:
        current = {"text": "旧人格"}
        raw = "```json\n" + json.dumps(
            {
                "persona": "新人格",
                "style": {"tone": "更温柔"},
                "boundaries": ["不编造"],
                "change_reason": "更自然的语气",
            },
            ensure_ascii=False,
        ) + "\n```"
        draft = parse_persona_draft(raw, current)
        self.assertIsNotNone(draft)
        assert draft is not None
        self.assertEqual(draft["persona"], "新人格")

        same = json.dumps(
            {
                "persona": "旧人格",
                "style": {},
                "boundaries": [],
                "change_reason": "不变",
            },
            ensure_ascii=False,
        )
        self.assertIsNone(parse_persona_draft(same, current))

    def test_parse_rejects_malformed_or_unknown_output(self) -> None:
        for raw in (
            "not json",
            json.dumps({"persona": "x", "style": {}, "boundaries": [], "change_reason": "x", "extra": 1}),
            json.dumps({"persona": "", "style": {}, "boundaries": [], "change_reason": "x"}),
        ):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    parse_persona_draft(raw, {"text": "旧"})


class PersonaSynthesisServiceTest(PersonaCase):
    def service(self, fake: _FakeModel, **config) -> MaintenanceService:
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
            config=_config(defaults),
            persona_model=factory,
            clock=datetime.datetime.now,
            proposals=self.db.persona_proposals,
            subject_key=lambda: self.subject_key,
        )

    def bootstrap(self, with_corpus: bool = False) -> None:
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(_direct_seed(with_corpus))

    def add_public_memory(self) -> None:
        now = "2026-10-25T11:59:00"
        art = make(
            "memory",
            {"text": "他最近喜欢在晚上散步", "level": "scene", "about": "other"},
            scope="shared",
            said_by="owner",
            strength=Strength(weight=2.0, confidence=1.0),
            lineage=Lineage(sources=("s1", "s2")),
            time=TimeSpan(created=now, updated=now),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=("s1", "s2")
        )
        self.cache.put(art)

    def test_weekly_writes_one_new_revision_on_same_lineage(self) -> None:
        self.bootstrap(with_corpus=True)
        initial = self.cache.active("persona")[0]
        self.assertIn("corpus", initial.payload)
        self.add_public_memory()
        fake = _FakeModel(
            json.dumps(
                {
                    "persona": "你是大肥鱼，温柔、嘴硬，也会记得陪他散步。",
                    "style": {"tone": "温柔嘴硬"},
                    "boundaries": ["不伪造用户经历"],
                    "change_reason": "加入最近散步的陪伴方式",
                },
                ensure_ascii=False,
            )
        )
        import asyncio

        result = asyncio.run(self.service(fake).weekly())
        self.assertFalse(result["persona"])
        self.assertEqual(result["persona_result"]["status"], "proposed")
        proposal = self.pending_proposals()[0]
        self.assertEqual(len(self.pending_proposals()), 1)
        self.assertEqual(proposal["base_revision"], initial.header.revision)
        self.assertEqual(proposal["old_text"], initial.payload["text"])
        self.assertIn("散步", proposal["new_text"])
        self.assertEqual(self.cache.active("persona")[0].header.revision, 1)
        self.assertEqual(self.cache.active("persona")[0].payload["text"], initial.payload["text"])
        self.approve_pending()
        active = self.cache.active("persona")[0]
        self.assertEqual(active.header.id, initial.header.id)
        self.assertEqual(active.header.revision, 2)
        self.assertEqual(active.payload["text"], proposal["new_text"])
        self.assertEqual(active.payload["origin"], "seed")
        self.assertEqual(len(active.payload["corpus"]), 12)
        self.assertEqual(active.payload["corpus_count"], 12)
        self.assertEqual(active.payload["corpus_hash"], initial.payload["corpus_hash"])
        self.assertTrue(trusted_self_persona(active))
        self.assertIn("散步", fake.request.prompt)
        timeline = StatusService(
            artifacts=self.db.artifacts, ledger=self.db.ledger
        ).persona()
        self.assertEqual(timeline["origin"], "seed")
        self.assertEqual(timeline["text"], proposal["new_text"])
        self.assertEqual(timeline["revisions"][-1]["origin"], "seed")

    def test_rollback_restores_seed_and_synthesized_revisions(self) -> None:
        self.bootstrap()
        initial = self.cache.active("persona")[0]
        self.add_public_memory()
        fake = _FakeModel(
            json.dumps(
                {
                    "persona": "你是大肥鱼，温柔、嘴硬，也会记得陪他散步。",
                    "style": {"tone": "温柔嘴硬"},
                    "boundaries": ["不伪造用户经历"],
                    "change_reason": "加入散步",
                },
                ensure_ascii=False,
            )
        )
        import asyncio

        asyncio.run(self.service(fake).weekly())
        proposal = self.approve_pending()
        self.assertEqual(self.cache.active("persona")[0].payload["text"], proposal["new_text"])
        manager = ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )
        manager.rollback_persona(
            {"id": initial.header.id, "revision": 1, "reason": "回到初始", "confirmed": True}
        )
        seed = self.cache.active("persona")[0]
        self.assertEqual(seed.header.revision, 3)
        self.assertEqual(seed.payload["origin"], "seed")
        self.assertTrue(trusted_self_persona(seed))

        manager.rollback_persona(
            {"id": initial.header.id, "revision": 2, "reason": "恢复合成版", "confirmed": True}
        )
        synthetic = self.cache.active("persona")[0]
        self.assertEqual(synthetic.header.revision, 4)
        self.assertEqual(synthetic.payload["origin"], "seed")
        self.assertEqual(synthetic.payload["text"], proposal["new_text"])
        self.assertTrue(trusted_self_persona(synthetic))

    def test_interval_and_failure_keep_old_persona(self) -> None:
        self.bootstrap()
        initial = self.cache.active("persona")[0]
        self.add_public_memory()
        fake = _FakeModel(
            json.dumps(
                {
                    "persona": "新人格",
                    "style": {},
                    "boundaries": [],
                    "change_reason": "变化",
                },
                ensure_ascii=False,
            )
        )
        import asyncio

        not_due = asyncio.run(
            self.service(fake, persona_synthesis_interval_days=7).weekly()
        )
        self.assertEqual(not_due["persona_result"]["status"], "not_due")
        self.assertEqual(fake.request, None)

        failed = asyncio.run(
            self.service(_FakeModel(error=RuntimeError("provider down"))).weekly()
        )
        self.assertEqual(failed["persona_result"]["status"], "failed")
        active = self.cache.active("persona")[0]
        self.assertEqual(active.header.id, initial.header.id)
        self.assertEqual(active.header.revision, 1)


if __name__ == "__main__":
    unittest.main()
