"""90-day deterministic persona lifecycle simulation."""
from __future__ import annotations

import asyncio
import datetime
import json
import time
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from persona_support import PersonaCase
from core.artifact import Lineage, TimeSpan, make
from core.graph import Graph
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService
from services.recall_service import RecallService


class _Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        return None


class _Model:
    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay
        self.prompts: list[str] = []

    async def complete(self, request):
        self.calls += 1
        self.prompts.append(str(getattr(request, "prompt", "")))
        if self.delay:
            await asyncio.sleep(self.delay)
        return SimpleNamespace(
            text=json.dumps(
                {
                    "persona": f"第 {self.calls} 次长期演化后的人格",
                    "style": {"tone": "稳定"},
                    "boundaries": ["不编造"],
                    "change_reason": f"第 {self.calls} 次长期演化",
                },
                ensure_ascii=False,
            ),
            usage_in=10,
            usage_cached=0,
            usage_out=5,
        )


def _corpus() -> list[dict[str, str]]:
    return [
        {
            "user": (
                f"第{i}个场景：今天发生了很多事情，我有点累，想和你说说心里话，"
                "工作上的压力和生活中的琐事都挤在一起，我现在只想安静一会儿。"
            ),
            "assistant": (
                f"先缓一缓，我在听。第{i}次也会陪着你，不用一个人扛着，"
                "你可以慢慢讲，不想说也没关系，我会在这里等你。"
            ),
        }
        for i in range(12)
    ]


def _seed() -> dict:
    return {
        "id": "long_horizon",
        "version": "1.0.0",
        "name": "长期人格",
        "persona": "你是长期测试人格。",
        "style": {"tone": "稳定"},
        "boundaries": ["不编造"],
        "corpus": _corpus(),
    }


class PersonaLongHorizonTest(PersonaCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = datetime.datetime.now().replace(microsecond=0)

    def service(self, model: _Model, **config) -> MaintenanceService:
        async def factory():
            return model

        defaults = {
            "persona_synthesis_enabled": True,
            "persona_synthesis_interval_days": 7,
            "persona_synthesis_evidence_limit": 8,
            "persona_synthesis_evidence_chars": 2400,
        }
        defaults.update(config)
        return MaintenanceService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            cache=self.cache,
            journal=_Journal(),
            task_id=lambda: "long",
            logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            config=lambda key, default: defaults.get(key, default),
            persona_model=factory,
            clock=lambda: self.base,
        )

    def bootstrap(self) -> str:
        result = ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(_seed())
        return result["id"]

    def add_shared_memory(self, day: int) -> None:
        now = (self.base + datetime.timedelta(days=day)).isoformat(timespec="seconds")
        art = make(
            "memory",
            {"text": f"第 {day} 天的公开长期事件", "level": "scene", "about": "other"},
            scope="shared",
            said_by="owner",
            lineage=Lineage(sources=(f"s{day}",)),
            time=TimeSpan(created=now, updated=now),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=(f"s{day}",)
        )
        self.cache.put(art)

    def add_private_marker(self, text: str, *, shareable: str = "private_only") -> None:
        now = self.base.isoformat(timespec="seconds")
        art = make(
            "memory",
            {"text": text, "level": "scene", "about": "other"},
            scope="private" if shareable == "private_only" else "shared",
            shareable=shareable,
            said_by="owner",
            lineage=Lineage(sources=("s_private",)),
            time=TimeSpan(created=now, updated=now),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=("s_private",)
        )
        self.cache.put(art)

    def restart(self) -> None:
        path = self.db.path
        self.db.close()
        from store import open_store
        from store.cache import Cache

        self.db = open_store(path)
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.cache.load()

    def recall(self):
        return RecallService(
            cache=self.cache,
            graph=Graph(self.db.artifacts),
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            budget=SimpleNamespace(injection_chars=600),
            config={}.get,
            owner_umo=lambda: "",
        ).build("你好", private=True, speaker="owner", dry_run=True)

    def sync(self, service: MaintenanceService) -> None:
        service.artifacts = self.db.artifacts
        service.sources = self.db.sources
        service.cache = self.cache
        service.clock = lambda: self.base

    def manager(self) -> ManagementService:
        return ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        )

    @staticmethod
    def trusted(art) -> bool:
        from core.bot_behavior import trusted_self_persona

        return trusted_self_persona(art)

    def test_90_day_lifecycle_with_checkpoints_rollbacks_and_restarts(self) -> None:
        persona_id = self.bootstrap()
        model = _Model()
        service = self.service(model)
        checkpoints: dict[int, int] = {}
        concurrent_days: list[int] = []
        started = time.monotonic()

        with patch(
            "core.artifact._now",
            side_effect=lambda: self.base.isoformat(timespec="microseconds"),
        ):
            for day in range(1, 91):
                self.base = self.base + datetime.timedelta(days=1)
                self.add_shared_memory(day)
                if day == 50:
                    self.add_private_marker("PRIVATE_EVIDENCE_MARKER")
                    self.add_private_marker(
                        "SECRET_EVIDENCE_MARKER", shareable="secret"
                    )
                self.sync(service)
                before = self.cache.active("persona")[0].header.revision

                if day == 45:
                    # Two weekly attempts race on the same base revision.
                    other = self.service(
                        _Model(delay=0.02), persona_synthesis_interval_days=0
                    )
                    racer = self.service(
                        _Model(delay=0.02), persona_synthesis_interval_days=0
                    )
                    results = asyncio.run(self.weekly_pair(racer, other))
                    statuses = sorted(
                        result["persona_result"]["status"] for result in results
                    )
                    self.assertEqual(statuses, ["failed", "updated"])
                    self.assertEqual(
                        self.cache.active("persona")[0].header.revision, before + 1
                    )
                    concurrent_days.append(day)
                else:
                    asyncio.run(service.weekly())

                active = self.cache.active("persona")
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0].header.id, persona_id)

                if day in (30, 60):
                    self.manager().rollback_persona(
                        {
                            "id": persona_id,
                            "revision": 1,
                            "reason": f"第 {day} 天回滚到 seed",
                            "confirmed": True,
                        }
                    )
                    restored = self.cache.active("persona")[0]
                    self.assertEqual(restored.header.id, persona_id)
                    self.assertEqual(restored.payload["origin"], "seed")
                    block, _info = self.recall()
                    self.assertIn(str(restored.payload["text"]), block)

                if day == 75:
                    self.manager().rollback_persona(
                        {
                            "id": persona_id,
                            "revision": 2,
                            "reason": "第 75 天回滚到合成版",
                            "confirmed": True,
                        }
                    )
                    restored = self.cache.active("persona")[0]
                    self.assertEqual(restored.header.id, persona_id)
                    self.assertEqual(restored.payload["origin"], "dream")
                    block, _info = self.recall()
                    self.assertIn(str(restored.payload["text"]), block)

                if day in (30, 60, 90):
                    self.restart()
                    self.sync(service)
                    active = self.cache.active("persona")
                    self.assertEqual(len(active), 1)
                    self.assertEqual(active[0].header.id, persona_id)

                if day in (7, 30, 60, 90):
                    current = self.cache.active("persona")[0]
                    checkpoints[day] = current.header.revision
                    payload = current.payload
                    self.assertEqual(payload["corpus_count"], 12)
                    self.assertEqual(len(payload["corpus_hash"]), 64)
                    if payload.get("origin") == "dream":
                        # Synthesized revisions carry only count/hash.
                        self.assertNotIn("corpus", payload)
                    else:
                        # A seed rollback restores the trusted seed payload.
                        self.assertEqual(len(payload["corpus"]), 12)
                    self.assertTrue(self.trusted(current))
                    block, info = self.recall()
                    self.assertIn(str(payload["text"]), block)
                    self.assertIn(current.header.id, info["final_ids"])

        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10.0)
        self.assertEqual(concurrent_days, [45])
        self.assertEqual(set(checkpoints), {7, 30, 60, 90})
        self.assertLess(checkpoints[7], checkpoints[30])
        self.assertLess(checkpoints[30], checkpoints[60])
        self.assertLess(checkpoints[60], checkpoints[90])
        self.assertGreaterEqual(model.calls, 8)
        self.assertLessEqual(model.calls, 20)

        persona = self.cache.active("persona")[0]
        self.assertEqual(persona.header.id, persona_id)
        self.assertEqual(persona.payload["origin"], "dream")
        self.assertEqual(persona.payload["synthesis"], "persona.v1")
        self.assertEqual(persona.payload["seed_id"], "long_horizon")
        self.assertTrue(persona.header.lineage.sources)
        self.assertTrue(persona.header.lineage.derived_from)
        self.assertTrue(model.prompts)
        for prompt in model.prompts:
            self.assertNotIn("PRIVATE_EVIDENCE_MARKER", prompt)
            self.assertNotIn("SECRET_EVIDENCE_MARKER", prompt)
        history = self.db.artifacts.history(persona_id)
        self.assertGreater(len(history), 10)
        self.assertEqual(
            [row["revision"] for row in history],
            list(range(1, len(history) + 1)),
        )
        origins = [row["payload"].get("origin") for row in history]
        self.assertIn("seed", origins)
        self.assertIn("dream", origins)
        self.assertEqual(len(self.cache.active("persona")), 1)

    async def weekly_pair(self, first, second):
        return await asyncio.gather(first.weekly(), second.weekly())


if __name__ == "__main__":
    unittest.main()
