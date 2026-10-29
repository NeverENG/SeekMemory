"""Exercise exact maintenance-plan retries and cache-only repairs.

验证精确维护计划重试及仅需缓存的补偿。
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from persona_support import PersonaCase
from app.contracts import ChatResponse
from core.artifact import Lineage, make, revise
from maintain.self_impression import build_self_impressions
from maintain.persona import distill_self_persona
from maintain.plans import RevisionWrite, RevisionPlan
from maintain.writer import MaintenanceWriter
from services.maintenance_service import MaintenanceService


class MaintenanceRecoveryTest(PersonaCase):
    def test_failed_self_impression_group_retries_identical_prepared_ids(self):
        self.three()
        writer = MaintenanceWriter(self.db.artifacts, self.cache, defer_cache_errors=True)
        attempted = []
        original = self.db.artifacts.commit_many

        def commit(writes, **kwargs):
            attempted.append(tuple(art.header.id for art, _revision, _sources in writes))
            if len(attempted) == 1:
                raise OSError("database failed")
            return original(writes, **kwargs)

        with patch.object(self.db.artifacts, "commit_many", side_effect=commit):
            with self.assertRaises(OSError):
                build_self_impressions(self.db.artifacts, self.db.sources, self.cache, writer=writer)
            self.assertEqual(writer.pending(), 1)
            self.assertEqual(writer.retry_writebacks(), 1)
        self.assertEqual(attempted[0], attempted[1])
        self.assertEqual(build_self_impressions(self.db.artifacts, self.db.sources, self.cache, writer=writer), 0)
        self.assertEqual(len(self.cache.by_level("impression")), 1)

    def test_cache_failure_blocks_new_plans_and_repairs_newest_self_impression(self):
        self.three()
        writer = MaintenanceWriter(self.db.artifacts, self.cache, defer_cache_errors=True)
        with patch.object(self.cache, "put", side_effect=OSError("cache failed")):
            self.assertEqual(build_self_impressions(self.db.artifacts, self.db.sources, self.cache, writer=writer), 1)
            self.assertEqual(writer.retry_writebacks(), 0)
            self.assertEqual(writer.retry_writebacks(), 0)
            with self.assertRaisesRegex(RuntimeError, "maintenance_writeback_pending"):
                build_self_impressions(self.db.artifacts, self.db.sources, self.cache, writer=writer)
            active = [art for art in self.db.artifacts.list("memory", "active")
                      if art.payload.get("level") == "impression"]
            self.assertEqual(len(active), 1)
            old = active[0]
            newest = revise(old, strength={**asdict(old.header.strength), "weight": 2.2})
            self.db.artifacts.commit(newest, expected_revision=old.header.revision, op="revise")
        self.assertEqual(writer.retry_writebacks(), 1)
        self.assertEqual(self.cache.get(newest.header.id), newest)
        self.assertEqual(build_self_impressions(self.db.artifacts, self.db.sources, self.cache, writer=writer), 0)
        self.assertEqual(self.db.artifacts.get(newest.header.id).header.revision, 2)

    def test_persona_cache_failure_does_not_create_parallel_personas(self):
        self.three()
        build_self_impressions(self.db.artifacts, self.db.sources, self.cache)
        writer = MaintenanceWriter(self.db.artifacts, self.cache, defer_cache_errors=True)
        with patch.object(self.cache, "put", side_effect=OSError("cache failed")):
            persona = distill_self_persona(self.db.artifacts, self.db.sources, self.cache, writer=writer)
            self.assertIsNotNone(persona)
            self.assertEqual(len(self.db.artifacts.list("persona", "active")), 1)
            with self.assertRaisesRegex(RuntimeError, "maintenance_writeback_pending"):
                distill_self_persona(self.db.artifacts, self.db.sources, self.cache, writer=writer)
        writer.retry_writebacks()
        second = distill_self_persona(self.db.artifacts, self.db.sources, self.cache, writer=writer)
        self.assertEqual(second.header.id, persona.header.id)
        self.assertEqual(second.header.revision, 1)
        self.assertEqual(len(self.db.artifacts.list("persona", "active")), 1)

    def test_conflicting_group_rolls_back_new_node_and_keeps_newer_head(self):
        base = self.episode()
        proposed = revise(base, payload={**base.payload, "text": "旧计划"})
        other = make("memory", {"level": "fact", "text": "不能部分创建的节点"})
        newer = revise(base, payload={**base.payload, "text": "较新修订"})
        self.db.artifacts.commit(newer, expected_revision=base.header.revision, op="revise")
        writer = MaintenanceWriter(self.db.artifacts, self.cache, defer_cache_errors=True)
        plan = RevisionPlan((RevisionWrite(other, 0, ()),
                             RevisionWrite(proposed, base.header.revision, tuple(base.header.lineage.sources))),
                            "merge", "test group atomicity")
        with self.assertRaises(ValueError):
            writer.execute(plan)
        self.assertIsNone(self.db.artifacts.get(other.header.id))
        self.assertEqual(self.db.artifacts.get(base.header.id), newer)
        self.assertEqual(writer.pending(), 0)

    def test_model_persona_commit_retry_never_calls_model_again(self):
        persona = make("persona", {"text": "你是温和的陪伴者", "origin": "seed", "seed_id": "test"},
                       subject_id="bot:self", scope="shared", shareable="public")
        self.seed(persona)
        public = make("memory", {"text": "一次公开的散步", "level": "scene"},
                      scope="shared", lineage=Lineage(sources=("u1", "a1")))
        self.seed(public)

        class Model:
            calls = 0

            async def complete(self, _request):
                self.calls += 1
                return ChatResponse(json.dumps({"persona": "你是温和且喜欢陪人散步的陪伴者", "style": {},
                                                "boundaries": [], "change_reason": "公开经历"}))

        model = Model()

        async def factory():
            return model

        class Journal:
            @contextmanager
            def span(self, *_args, **_kwargs):
                yield {}

            def record(self, *_args, **_kwargs):
                pass

        service = MaintenanceService(
            artifacts=self.db.artifacts, sources=self.db.sources, cache=self.cache, journal=Journal(),
            task_id=lambda: "", logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            persona_model=factory, config=lambda key, default: 0 if key == "persona_synthesis_interval_days" else default,
        )
        with patch.object(self.db.artifacts, "commit", side_effect=OSError("database failed")):
            result = asyncio.run(service._synthesize_persona_async())
            self.assertEqual(result["status"], "failed")
        self.assertEqual(service.retry_writebacks(), 1)
        self.assertEqual(model.calls, 1)
        self.assertEqual(self.db.artifacts.get(persona.header.id).header.revision, 2)


if __name__ == "__main__":
    unittest.main()
