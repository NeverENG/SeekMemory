"""Test context-recording commits and cache-only compensation through public entries.

通过公开入口验证上下文记录提交及仅需缓存的补偿。
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.budget import ContextBudget
from core.artifact import make, revise
from core.graph import Graph
from recall.designated import mark_given
from services.background_service import BackgroundService
from services.recall_service import RecallService
from store import open_store
from store.cache import Cache


class RecallWritebackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.session = "bot:FriendMessage:u"
        self.art = make("designated", {"text": "明确托付的清单正文", "trigger": "清单", "owner_umo": self.session})
        self.db.artifacts.commit(self.art, expected_revision=0, op="create")
        self.cache.put(self.art)
        self.service = RecallService(
            cache=self.cache, graph=Graph(self.db.artifacts), artifacts=self.db.artifacts,
            sources=self.db.sources, budget=ContextBudget(injection_chars=600),
            config=lambda _key, default: default, owner_umo=lambda: self.session,
        )
        self.block, self.info = self.service.query("清单", self.session, True, "u")

    def test_failed_commit_is_retained_and_retry_does_not_rebuild_context(self):
        with patch.object(self.db.artifacts, "commit", side_effect=OSError("database failed")):
            self.assertEqual(self.service.record_context_injection(self.block, self.info), 0)
            self.assertEqual(self.service.retry_writebacks(), 0)
            self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)
        with patch.object(self.service, "query", side_effect=AssertionError("unexpected query")):
            self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.service.retry_writebacks(), 0)
        self.assertEqual(self.db.artifacts.get(self.art.header.id).header.revision, 2)
        self.assertEqual(len(self.db.ledger.entries()), 2)

    def test_cache_failure_never_reinjects_or_recommits_and_repairs_latest_head(self):
        with patch.object(self.cache, "put", side_effect=OSError("cache failed")):
            self.assertEqual(self.service.record_context_injection(self.block, self.info), 1)
            self.assertEqual(self.service.retry_writebacks(), 0)
            self.assertEqual(self.service.retry_writebacks(), 0)
            block, _ = self.service.query("清单", self.session, True, "u")
            self.assertNotIn(self.art.payload["text"], block)
            self.assertEqual(self.cache.get(self.art.header.id), self.art)
            current = self.db.artifacts.get(self.art.header.id)
            newer = revise(current, payload={**current.payload, "text": "后来修订的清单正文"})
            self.db.artifacts.commit(newer, expected_revision=current.header.revision, op="revise")
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.cache.get(self.art.header.id), newer)
        self.assertEqual(self.service.retry_writebacks(), 0)
        self.assertEqual(len(self.db.ledger.entries()), 3)

    def test_newer_revision_is_not_overwritten_by_old_pending_inclusion(self):
        with patch.object(self.db.artifacts, "commit", side_effect=OSError("database failed")):
            self.service.record_context_injection(self.block, self.info)
        newer = revise(self.art, payload={**self.art.payload, "text": "改为另一个正文"})
        self.db.artifacts.commit(newer, expected_revision=1, op="revise")
        self.assertEqual(self.service.retry_writebacks(), 1)
        self.assertEqual(self.db.artifacts.get(self.art.header.id), newer)
        self.assertFalse(newer.payload.get("given"))
        self.assertEqual(len(self.db.ledger.entries()), 2)

    def test_stale_query_receipt_cannot_mark_new_version_given(self):
        newer = revise(self.art, payload={**self.art.payload, "text": "新正文尚未进入上下文"})
        self.db.artifacts.commit(newer, expected_revision=1, op="revise")
        self.assertEqual(self.service.record_context_injection(self.block, self.info), 0)
        self.assertEqual(self.db.artifacts.get(self.art.header.id), newer)

    def test_failed_designated_head_lookup_withholds_body_without_hidden_write(self):
        with patch.object(self.db.artifacts, "get", side_effect=OSError("read failed")), \
             patch.object(self.db.artifacts, "commit", side_effect=AssertionError("hidden write")):
            block, _ = self.service.query("清单", self.session, True, "u")
        self.assertNotIn(self.art.payload["text"], block)

    def test_legacy_marker_returns_commit_count_despite_cache_failure(self):
        with patch.object(self.cache, "put", side_effect=OSError("cache failed")):
            self.assertEqual(mark_given(self.db.artifacts, self.cache, [self.art], self.block), 1)
            self.assertEqual(mark_given(self.db.artifacts, self.cache, [self.art], self.block), 0)
        self.assertEqual(len(self.db.ledger.entries()), 2)

    async def test_background_shutdown_retries_context_records_with_extraction_off(self):
        with patch.object(self.db.artifacts, "commit", side_effect=OSError("database failed")):
            self.service.record_context_injection(self.block, self.info)
        background = BackgroundService(
            jobs=None, checkpoint=None, buffer=None, capacity=None, ingest=None, maintenance=None,
            dream=None, runtime_worker=None, journal=None, config=lambda _key, _default: False,
            logger=logging.getLogger(__name__), context_writer=self.service,
        )
        await background.stop()
        self.assertTrue(self.db.artifacts.get(self.art.header.id).payload.get("given"))
        self.assertEqual(self.service.retry_writebacks(), 0)


if __name__ == "__main__":
    unittest.main()
