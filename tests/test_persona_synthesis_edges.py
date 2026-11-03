"""Small edge/contract tests for Dream persona synthesis and rollback."""
from __future__ import annotations

import asyncio
import datetime
import json
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

from persona_support import PersonaCase
from app.dream import DreamCycle
from core.artifact import Lineage, TimeSpan, make
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService


class _Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        return None


class _FakeModel:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error
        self.calls = 0

    async def complete(self, _request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(text=self.text)


def _seed() -> dict:
    return {
        "id": "edge_persona",
        "version": "1.0.0",
        "name": "边界测试人格",
        "persona": "你是用于边界测试的人格。",
        "style": {"tone": "稳定"},
        "boundaries": ["不编造"],
    }


def _config(values: dict):
    return lambda key, default: values.get(key, default)


def _model_text(day: int = 1) -> str:
    return json.dumps(
        {
            "persona": f"第 {day} 天的人格",
            "style": {"tone": "稳定"},
            "boundaries": ["不编造"],
            "change_reason": f"第 {day} 天更新",
        },
        ensure_ascii=False,
    )


class _DreamStore:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def get(self, date):
        return self.runs.get(date)

    def begin(self, date, now=""):
        self.runs[date] = {"date": date, "status": "running"}
        return True

    def finish(self, date, *, status="done", batches=0, written=0,
               errors=None, summary=None, now=""):
        self.runs[date] = {
            "status": status,
            "summary": summary or {},
            "errors": errors or [],
        }

    def recent(self, limit=7):
        return list(self.runs.values())[:limit]


class PersonaSynthesisEdgeTest(PersonaCase):
    def bootstrap(self) -> None:
        ManagementService(
            self.db.artifacts, self.db.sources, self.db.ledger, self.cache, None
        ).bootstrap_persona(_seed())

    def add_shared_memory(self, text: str = "最近在整理长期关系") -> None:
        art = make(
            "memory",
            {"text": text, "level": "scene", "about": "other"},
            scope="shared",
            said_by="owner",
            lineage=Lineage(sources=("s1", "s2")),
            time=TimeSpan(
                created=datetime.datetime.now().isoformat(timespec="seconds"),
                updated=datetime.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        self.db.artifacts.commit(
            art, expected_revision=0, op="create", source_ids=("s1", "s2")
        )
        self.cache.put(art)

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

    def test_enabled_false_makes_no_call_or_revision(self) -> None:
        self.bootstrap()
        self.add_shared_memory()
        fake = _FakeModel(_model_text())
        result = asyncio.run(self.service(fake, persona_synthesis_enabled=False).weekly())
        self.assertEqual(result["persona_result"]["status"], "disabled")
        self.assertEqual(fake.calls, 0)
        self.assertEqual(len(self.cache.active("persona")), 1)
        self.assertEqual(self.cache.active("persona")[0].header.revision, 1)

    def test_interval_age_boundary_is_exact(self) -> None:
        base = datetime.datetime(2026, 1, 1, 12, 0, 0)
        art = make(
            "persona",
            {"text": "old"},
            time=TimeSpan(created=base.isoformat(), updated=base.isoformat()),
        )
        service = self.service(_FakeModel())
        service.clock = lambda: base + datetime.timedelta(days=6, hours=21, minutes=36)
        self.assertAlmostEqual(service._persona_age_days(art), 6.9, places=2)
        service.clock = lambda: base + datetime.timedelta(days=7)
        self.assertAlmostEqual(service._persona_age_days(art), 7.0, places=2)

    def test_no_evidence_and_same_text_do_not_write(self) -> None:
        self.bootstrap()
        fake = _FakeModel(_model_text())
        no_evidence = asyncio.run(self.service(fake).weekly())
        self.assertEqual(no_evidence["persona_result"]["status"], "no_evidence")
        self.assertEqual(fake.calls, 0)

        self.add_shared_memory()
        same = _FakeModel(json.dumps(
            {
                "persona": "你是用于边界测试的人格。",
                "style": {},
                "boundaries": [],
                "change_reason": "不变",
            },
            ensure_ascii=False,
        ))
        result = asyncio.run(self.service(same).weekly())
        self.assertEqual(result["persona_result"]["status"], "unchanged")
        self.assertEqual(len(self.cache.active("persona")), 1)
        self.assertEqual(self.cache.active("persona")[0].header.revision, 1)

    def test_commit_failure_keeps_old_persona_and_cache(self) -> None:
        self.bootstrap()
        self.add_shared_memory()
        old = self.cache.active("persona")[0]
        real_create = self.db.persona_proposals.create

        def fail_proposal(**_kwargs):
            raise RuntimeError("disk failure")

        self.db.persona_proposals.create = fail_proposal
        try:
            result = asyncio.run(self.service(_FakeModel(_model_text())).weekly())
        finally:
            self.db.persona_proposals.create = real_create
        self.assertEqual(result["persona_result"]["status"], "failed")
        self.assertEqual(self.pending_proposals(), [])
        active = self.cache.active("persona")[0]
        self.assertEqual(active.header.id, old.header.id)
        self.assertEqual(active.header.revision, 1)

    def test_provider_missing_usage_is_tolerated_and_recorded_as_zero(self) -> None:
        self.bootstrap()
        self.add_shared_memory()
        result = asyncio.run(self.service(_FakeModel(_model_text())).weekly())
        self.assertEqual(result["persona_result"]["status"], "proposed")
        self.assertEqual(len(self.pending_proposals()), 1)
        self.assertEqual(result["persona_result"]["usage"], {"in": 0, "cached": 0, "out": 0})

    def test_dream_summary_keeps_persona_result(self) -> None:
        store = _DreamStore()
        pending = {"value": 1}

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            pending["value"] = 0
            return 0, 1

        async def maintain():
            return {
                "persona": True,
                "persona_result": {
                    "status": "updated",
                    "revision": 2,
                    "usage": {"in": 10, "cached": 0, "out": 5},
                },
            }

        import asyncio

        result = asyncio.run(
            DreamCycle(
                store,
                lambda key, default: {
                    "dream_time": "03:30",
                    "dream_enabled": True,
                }.get(key, default),
            ).run(
                flush,
                pending=lambda: pending["value"],
                maintain=maintain,
                now=datetime.datetime(2026, 10, 25, 4, 0),
            )
        )
        self.assertEqual(result.status, "done")
        summary = store.runs["2026-10-25"]["summary"]
        self.assertEqual(summary["persona_result"]["status"], "updated")
        self.assertEqual(summary["persona_result"]["usage"]["in"], 10)

    def test_provider_error_and_invalid_output_keep_old_persona(self) -> None:
        self.bootstrap()
        self.add_shared_memory()
        for fake in (
            _FakeModel(error=TimeoutError("timeout")),
            _FakeModel("not json"),
            _FakeModel(json.dumps({"persona": "x", "style": {}, "boundaries": [], "change_reason": "x", "extra": 1})),
        ):
            with self.subTest(fake=fake):
                result = asyncio.run(self.service(fake).weekly())
                self.assertEqual(result["persona_result"]["status"], "failed")
                self.assertEqual(len(self.cache.active("persona")), 1)
                self.assertEqual(self.cache.active("persona")[0].header.revision, 1)


if __name__ == "__main__":
    unittest.main()
