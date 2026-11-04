"""Persist normalized extraction, reopen storage, and query disclosed context.

保存规范化抽取、重新打开存储并查询披露结果，保留旧记录及只读召回。
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.budget import ContextBudget
from core.artifact import Lineage, make
from core.graph import Graph
from core.source import Source
from perceive.buffer import Buffer
from services.ingest_service import IngestService
from services.recall_service import RecallService
from store import open_store
from store.cache import Cache

SESSION = "test:FriendMessage:u1"
FACT = "最喜欢的饮料是茉莉花茶，习惯不加糖"


class Journal:
    """Discard test diagnostics without changing the ingest boundary."""

    def span(self, *_args, **_kwargs):
        return nullcontext({})

    def record(self, *_args, **_kwargs):
        pass


class SubjectIdentityIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / "memory.db")
        self.db = open_store(self.path)
        self.addCleanup(lambda: self.db.close())
        self.cache = Cache(self.db.artifacts)
        self.source = Source("s1", "turn1", SESSION, "u1", "user", FACT,
                             "2026-10-31T12:00:00+08:00")

    def extract(self, *, subject: str = "user(u1)", level: str = "fact"):
        buffer = Buffer(extraction=self.db.extraction)
        buffer.add(SESSION, self.source.text, sender=self.source.speaker_id,
                   at=self.source.at, source=self.source)

        async def provider_for(_session):
            raise AssertionError("pull-style extraction must not call a model")

        service = IngestService(
            buffer=buffer, artifacts=self.db.artifacts, sources=self.db.sources,
            extraction=self.db.extraction, cache=self.cache, graph=None,
            journal=Journal(), config=lambda _key, default: default,
            provider_for=provider_for, owner_id=lambda: "u1",
            logger=logging.getLogger(__name__),
        )
        task = service.next_extraction_task()
        self.assertIsNotNone(task)
        self.assertIn("user(u1)[s1]", task.prompt)
        raw = json.dumps([{
            "level": level, "text": FACT, "tags": "饮料 喜欢 糖",
            "subject_kind": "owner", "subject_id": subject,
            "evidence_source_ids": [self.source.id],
        }])
        outcome = service.commit_extraction(task.source_ids, raw)
        self.assertEqual(outcome.written, 1, outcome.errors)
        self.assertEqual(buffer.items, [])
        return next(art for art in self.cache.active("memory") if art.payload["text"] == FACT)

    def reopen(self) -> RecallService:
        self.db.close()
        self.db = open_store(self.path)
        self.cache = Cache(self.db.artifacts)
        self.cache.load()
        return RecallService(
            cache=self.cache, graph=Graph(self.db.artifacts),
            artifacts=self.db.artifacts, sources=self.db.sources,
            budget=ContextBudget(), config={"explore_rate": 0}.get,
            owner_umo=lambda: SESSION,
        )

    def test_new_fact_survives_reopen_and_discloses_only_to_same_context(self) -> None:
        art = self.extract()
        recall = self.reopen()
        persisted = self.db.artifacts.get(art.header.id)
        self.assertEqual(persisted.header.subject_id, "u1")
        self.assertEqual(persisted.payload["subject_id"], "u1")
        self.assertEqual(persisted.header.lineage.sources, (self.source.id,))
        self.assertEqual(len(self.db.artifacts.history(art.header.id)), 1)
        self.assertEqual(self.db.sources.sources_by_ids(["s1"])["s1"], self.source)
        ledger = [dict(row) for row in self.db.ledger.entries()]
        self.assertEqual(len(ledger), 1)

        block, info = recall.query("我喜欢什么饮料，糖怎么加？", SESSION, True, "u1")
        self.assertIn("茉莉花茶", block)
        self.assertIn("不加糖", block)
        self.assertEqual(info["disclosure"].get(art.header.id), "full")
        for session, speaker in ((SESSION, "u2"), ("test:GroupMessage:g2", "u1")):
            with self.subTest(session=session, speaker=speaker):
                block, info = recall.query("我喜欢什么饮料，糖怎么加？", session, True, speaker)
                self.assertNotIn("茉莉花茶", block)
                self.assertNotEqual(info["disclosure"].get(art.header.id), "full")
        self.assertEqual([dict(row) for row in self.db.ledger.entries()], ledger)
        self.assertEqual(self.db.artifacts.get(art.header.id), persisted)
        self.assertTrue(self.db.ledger.verify())

    def test_unknown_wrapper_does_not_gain_owner_disclosure(self) -> None:
        art = self.extract(subject="user(unknown)")
        recall = self.reopen()
        block, info = recall.query("我喜欢什么饮料，糖怎么加？", SESSION, True, "u1")
        self.assertEqual(self.db.artifacts.get(art.header.id).header.subject_id, "user(unknown)")
        self.assertNotIn("茉莉花茶", block)
        self.assertNotEqual(info["disclosure"].get(art.header.id), "full")

    def test_normalized_impression_still_obeys_cross_session_pinned_disclosure(self) -> None:
        art = self.extract(level="impression")
        recall = self.reopen()
        block, info = recall.query("hello", "test:GroupMessage:g2", False, "u1")
        self.assertIn(art.header.id, info["pinned_ids"])
        self.assertNotIn("茉莉花茶", block)
        self.assertNotEqual(info["disclosure"].get(art.header.id), "full")

    def test_new_extraction_does_not_revise_legacy_wrapped_artifact(self) -> None:
        self.db.sources.append_sources([self.source])
        legacy = make(
            "memory", {"level": "fact", "text": "旧格式样本", "subject_id": "user(u1)"},
            scope="private", subject_id="user(u1)", lineage=Lineage(sources=("s1",)),
        )
        self.db.artifacts.commit(legacy, expected_revision=0, op="create", source_ids=("s1",))
        self.cache.put(legacy)
        history = self.db.artifacts.history(legacy.header.id)
        ledger = [dict(row) for row in self.db.ledger.entries()]
        self.extract()
        self.reopen()
        self.assertEqual(self.db.artifacts.get(legacy.header.id), legacy)
        self.assertEqual(self.db.artifacts.history(legacy.header.id), history)
        self.assertEqual([dict(row) for row in self.db.ledger.entries()][:1], ledger)
        self.assertTrue(self.db.ledger.verify())


if __name__ == "__main__":
    unittest.main()
