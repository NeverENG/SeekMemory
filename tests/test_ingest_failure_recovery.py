"""Exercise prepared extraction recovery through service/store interfaces.

通过服务及存储接口验证已准备抽取计划的恢复。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import ChatResponse
from app.dream import DreamCycle
from core.artifact import revise
from core.source import Source
from perceive.buffer import Buffer
from services.background_service import BackgroundService
from services.ingest_service import IngestService
from store import open_store
from store.cache import Cache


class Journal:
    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        pass


class Model:
    def __init__(self, rows=None):
        self.calls = 0
        self.rows = rows if rows is not None else [
            {"level": "fact", "text": "用户周末去医院检查眼睛"},
            {"level": "fact", "text": "用户养了两只金毛犬"},
        ]

    async def complete(self, _request):
        self.calls += 1
        return ChatResponse(json.dumps(self.rows), usage_in=10, usage_out=5)

    async def text_chat(self, **_kwargs):
        response = await self.complete(None)
        return SimpleNamespace(completion_text=response.text, usage_in=10, usage_out=5)


class IngestWritebackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.buffer = Buffer(extraction=self.db.extraction)
        self.cache = Cache(self.db.artifacts)
        self.model = Model()

        async def provider_for(_session):
            return self.model

        self.service = IngestService(
            buffer=self.buffer, artifacts=self.db.artifacts, sources=self.db.sources,
            extraction=self.db.extraction, cache=self.cache, graph=None, journal=Journal(),
            config=lambda _key, default: default, provider_for=provider_for,
            owner_id=lambda: "u", logger=logging.getLogger(__name__),
        )
        self.add_source("s1")

    def add_source(self, entity):
        source = Source(entity, entity, "private", "u", "user", "我周末要去检查眼睛，也要照顾家里的金毛犬",
                        "2026-10-29T10:00:00")
        self.db.sources.append_sources([source])
        self.buffer.add(source.session_id, source.text, source=source)

    async def test_partial_commit_resumes_original_plan_without_model_replay(self):
        original = self.db.artifacts.commit
        attempts = []

        def commit(art, **kwargs):
            attempts.append(art.header.id)
            if len(attempts) == 2:
                raise OSError("database unavailable")
            return original(art, **kwargs)

        with patch.object(self.db.artifacts, "commit", side_effect=commit):
            first = await self.service.extract(self.buffer.items, self.model)
            self.assertEqual(first.written, 1)
            self.assertTrue(first.retryable)
            second = await self.service.extract(self.buffer.items, self.model)
        self.assertEqual(second.written, 1)
        self.assertFalse(second.retryable)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.db.artifacts.count(), 2)
        self.assertEqual(len(self.db.ledger.entries()), 2)
        self.assertNotIn(attempts[0], attempts[1:])

    async def test_repeated_cache_failure_repairs_latest_head_and_keeps_new_input(self):
        rows = list(self.buffer.items)
        with patch.object(self.cache, "put", side_effect=OSError("cache unavailable")):
            first = await self.service.extract(rows, self.model, confirm_queue=True)
            self.assertEqual(first.written, 2)
            self.assertTrue(first.retryable)
            self.assertEqual(self.service.retry_writebacks(), 0)
            self.assertEqual(self.service.retry_writebacks(), 0)
            current = self.db.artifacts.get(first.ids[0])
            latest = revise(current, payload={**current.payload, "text": "更新后的事实"})
            self.db.artifacts.commit(latest, expected_revision=current.header.revision, op="revise")
            self.add_source("s2")
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.cache.get(latest.header.id), latest)
        self.assertEqual([row.source_id for row in self.buffer.items], ["s2"])
        self.assertEqual(self.db.artifacts.count(), 2)
        self.assertEqual(len(self.db.ledger.entries()), 3)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.service.usage_snapshot()["calls"], 1)

    async def test_queue_failure_does_not_recreate_committed_memories(self):
        with patch.object(self.db.extraction, "mark_extraction_succeeded", side_effect=OSError("queue unavailable")):
            with self.assertRaises(RuntimeError):
                await self.service.flush("test")
            self.assertEqual(self.db.artifacts.count(), 2)
            self.assertEqual(self.service.retry_writebacks(), 0)
            self.assertEqual(self.db.extraction.queue_counts().get("pending"), 1)
            self.assertEqual(await self.service.flush("test"), (0, 0))
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.buffer.items, [])
        self.assertEqual(self.db.artifacts.count(), 2)
        self.assertEqual(len(self.db.ledger.entries()), 2)
        self.assertEqual(self.model.calls, 1)

    async def test_empty_model_result_retains_only_queue_confirmation(self):
        self.model.rows = []
        with patch.object(self.db.extraction, "mark_extraction_succeeded", side_effect=OSError("queue unavailable")):
            outcome = await self.service.extract(list(self.buffer.items), self.model, confirm_queue=True)
            self.assertTrue(outcome.retryable)
            self.assertEqual(self.db.artifacts.count(), 0)
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.model.calls, 1)
        self.assertEqual(self.buffer.items, [])

    async def test_dream_failure_reports_already_committed_memories(self):
        cycle = DreamCycle(self.db.dreams, lambda _key, default: default)
        with patch.object(self.db.extraction, "mark_extraction_succeeded", side_effect=OSError("queue unavailable")):
            result = await cycle.run(
                self.service.flush, lambda: len(self.buffer.items),
                now=datetime.datetime(2026, 10, 29, 4), usage=self.service.usage_snapshot,
            )
        self.assertEqual(result.status, "failed")
        self.assertEqual((result.written, result.batches), (2, 1))
        self.assertEqual(self.db.dreams.get(result.date)["written"], 2)
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.model.calls, 1)

    async def test_cancelled_diagnostic_after_commit_resumes_without_duplicate(self):
        @contextmanager
        def stage(name):
            yield {}
            if name == "artifact.persist":
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await self.service.extract(self.buffer.items, self.model, confirm_queue=True, stage=stage)
        self.assertEqual(self.db.artifacts.count(), 1)
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.db.artifacts.count(), 2)
        self.assertEqual(len(self.db.ledger.entries()), 2)
        self.assertEqual(self.model.calls, 1)

    async def test_optional_enrichment_failure_does_not_reclassify_commit(self):
        with patch("services.ingest_service.link_new", side_effect=RuntimeError("graph unavailable")):
            outcome = await self.service.extract(self.buffer.items, self.model, confirm_queue=True)
        self.assertEqual(outcome.written, 2)
        self.assertFalse(outcome.retryable)
        self.assertEqual(self.buffer.items, [])
        self.assertEqual(self.service.retry_writebacks(), 0)
        self.assertEqual(self.model.calls, 1)

    async def test_model_failure_without_commits_preserves_original_exception_type(self):
        with patch.object(self.model, "text_chat", side_effect=ValueError("provider unavailable")):
            with self.assertRaises(ValueError):
                await self.service.flush("test")
        self.assertEqual(self.db.artifacts.count(), 0)
        self.assertEqual(len(self.buffer.items), 1)

    async def test_broken_diagnostics_do_not_lose_successful_flush_counts(self):
        with patch.object(self.service.journal, "span", side_effect=OSError("diagnostic unavailable")), \
             patch.object(self.service.journal, "record", side_effect=OSError("diagnostic unavailable")), \
             patch.object(self.service.logger, "info", side_effect=OSError("logger unavailable")):
            self.assertEqual(await self.service.flush("test"), (2, 1))
        self.assertEqual(self.buffer.items, [])
        self.assertEqual(self.db.artifacts.count(), 2)
        self.assertEqual(self.model.calls, 1)

    async def test_disabled_extraction_still_runs_compensation_and_shutdown_attempt(self):
        with patch.object(self.db.extraction, "mark_extraction_succeeded", side_effect=OSError("queue unavailable")):
            await self.service.extract(self.buffer.items, self.model, confirm_queue=True)
        background = BackgroundService(
            jobs=None, checkpoint=None, buffer=self.buffer, capacity=None, ingest=self.service,
            maintenance=None, dream=None, runtime_worker=None, journal=Journal(),
            config=lambda key, default: False if key == "ingest_enabled" else default,
            logger=logging.getLogger(__name__),
        )
        calls = 0

        async def sleep(_duration):
            nonlocal calls
            calls += 1
            if calls > 1:
                raise asyncio.CancelledError

        with patch("services.background_service.asyncio.sleep", side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await background._ingest_loop()
        self.assertEqual(self.buffer.items, [])
        await background.stop()
        self.assertEqual(self.model.calls, 1)


if __name__ == "__main__":
    unittest.main()
