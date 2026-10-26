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
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService


class _Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        return None


class _Model:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, _request):
        self.calls += 1
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


def _seed() -> dict:
    return {
        "id": "long_horizon",
        "version": "1.0.0",
        "name": "长期人格",
        "persona": "你是长期测试人格。",
        "style": {"tone": "稳定"},
        "boundaries": ["不编造"],
    }


class PersonaLongHorizonTest(PersonaCase):
    def setUp(self) -> None:
        super().setUp()
        self.base = datetime.datetime.now().replace(microsecond=0)

    def service(self, model: _Model) -> MaintenanceService:
        async def factory():
            return model

        return MaintenanceService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            cache=self.cache,
            journal=_Journal(),
            task_id=lambda: "long",
            logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            config=lambda key, default: {
                "persona_synthesis_enabled": True,
                "persona_synthesis_interval_days": 7,
                "persona_synthesis_evidence_limit": 8,
                "persona_synthesis_evidence_chars": 2400,
            }.get(key, default),
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

    def restart(self) -> None:
        path = self.db.path
        self.db.close()
        from store import open_store
        from store.cache import Cache

        self.db = open_store(path)
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.cache.load()

    def test_90_day_lifecycle_with_checkpoints_rollbacks_and_restarts(self) -> None:
        persona_id = self.bootstrap()
        model = _Model()
        service = self.service(model)
        checkpoints: dict[int, int] = {}
        started = time.monotonic()

        with patch(
            "core.artifact._now",
            side_effect=lambda: self.base.isoformat(timespec="microseconds"),
        ):
            for day in range(1, 91):
                self.base = self.base + datetime.timedelta(days=1)
                self.add_shared_memory(day)
                service.artifacts = self.db.artifacts
                service.sources = self.db.sources
                service.cache = self.cache
                service.clock = lambda day=day: self.base
                asyncio.run(service.weekly())

                active = self.cache.active("persona")
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0].header.id, persona_id)

                if day in (30, 60):
                    ManagementService(
                        self.db.artifacts,
                        self.db.sources,
                        self.db.ledger,
                        self.cache,
                        None,
                    ).rollback_persona(
                        {
                            "id": persona_id,
                            "revision": 1,
                            "reason": f"第 {day} 天检查点回滚",
                            "confirmed": True,
                        }
                    )
                    active = self.cache.active("persona")
                    self.assertEqual(len(active), 1)
                    self.assertEqual(active[0].header.id, persona_id)
                    self.assertEqual(active[0].payload["origin"], "seed")

                if day in (30, 60, 90):
                    self.restart()
                    service.artifacts = self.db.artifacts
                    service.sources = self.db.sources
                    service.cache = self.cache
                    active = self.cache.active("persona")
                    self.assertEqual(len(active), 1)
                    self.assertEqual(active[0].header.id, persona_id)

                if day in (7, 30, 60, 90):
                    checkpoints[day] = self.cache.active("persona")[0].header.revision

        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 10.0)
        self.assertEqual(set(checkpoints), {7, 30, 60, 90})
        self.assertEqual(checkpoints[7], checkpoints[7])
        self.assertLessEqual(checkpoints[7], checkpoints[30])
        self.assertLessEqual(checkpoints[30], checkpoints[60])
        self.assertLessEqual(checkpoints[60], checkpoints[90])
        self.assertGreaterEqual(model.calls, 8)
        self.assertLessEqual(model.calls, 14)

        persona = self.cache.active("persona")[0]
        self.assertEqual(persona.header.id, persona_id)
        self.assertEqual(persona.payload["origin"], "dream")
        self.assertTrue(persona.payload["synthesis"] == "persona.v1")
        self.assertTrue(persona.header.lineage.sources)
        self.assertTrue(persona.header.lineage.derived_from)
        self.assertGreater(len(self.db.artifacts.history(persona_id)), 10)
        self.assertEqual(len(self.cache.active("persona")), 1)


if __name__ == "__main__":
    unittest.main()
