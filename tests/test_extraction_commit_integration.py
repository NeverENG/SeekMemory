"""Exercise pull-style extraction plan/commit through the kernel services.

验证拉取式抽取的 plan/commit：内核只生成提示词与任务编号，宿主回传模型输出后再走既有计划管线持久化。
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import content_of
from core.source import Source
from perceive.buffer import Buffer
from perceive.extract import ExtractionParseError
from services.ingest_service import IngestService
from store import open_store
from store.cache import Cache


class Journal:
    """Minimal service journal used by the ingest service / 供抽取服务使用的最小日志。"""

    @contextmanager
    def span(self, *_args, **_kwargs):
        yield {}

    def record(self, *_args, **_kwargs):
        pass


def _payload(source_id: str, subject_id: str = "user(u1)") -> str:
    """Build one valid fact item referencing the supplied Source ID / 构造一条引用给定原始消息的合法事实。"""
    return json.dumps([{
        "level": "fact",
        "text": "用户周末要去医院检查眼睛",
        "tags": "医院 检查 眼睛 周末",
        "about": "other",
        "subject_kind": "speaker",
        "subject_id": subject_id,
        "event_at": "2026-10-29T10:00:00",
        "confidence": 0.95,
        "arousal": 0.2,
        "valence": 0.0,
        "funny": 0.0,
        "first": True,
        "evidence_source_ids": [source_id],
    }], ensure_ascii=False)


class ExtractionCommitTest(unittest.TestCase):
    """Cover the pull-style task lifecycle against a real store / 在真实存储上覆盖拉取式任务生命周期。"""

    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.buffer = Buffer(extraction=self.db.extraction)
        self.cache = Cache(self.db.artifacts)

        async def provider_for(_session):
            raise AssertionError("pull-style tasks must never call the model")

        self.service = IngestService(
            buffer=self.buffer,
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            extraction=self.db.extraction,
            cache=self.cache,
            graph=None,
            journal=Journal(),
            config=lambda _key, default: default,
            provider_for=provider_for,
            owner_id=lambda: "u1",
            logger=logging.getLogger(__name__),
        )

    def add_source(self, entity: str = "s1", text: str = "我周末要去医院检查眼睛") -> str:
        """Admit one Source-backed pending row / 接纳一条带原始消息的待处理行。"""
        source = Source(
            entity, entity, "private", "u1", "user", text, "2026-10-29T10:00:00",
        )
        self.db.sources.append_sources([source])
        turn = self.buffer.add(source.session_id, source.text, source=source)
        assert turn is not None
        return turn.source_id

    def test_plan_commit_writes_memory_and_clears_queue(self) -> None:
        source_id = self.add_source()
        task = self.service.next_extraction_task()

        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task.source_ids, (source_id,))
        self.assertIn("我周末要去医院检查眼睛", task.prompt)
        self.assertIn("JSON", task.system_prompt)
        self.assertTrue(task.task_id)

        outcome = self.service.commit_extraction(task.source_ids, _payload(source_id))

        self.assertEqual(outcome.written, 1, outcome.errors)
        self.assertFalse(outcome.retryable)
        self.assertEqual(self.buffer.items, [])
        memories = [content_of(art) for art in self.cache.active("memory")]
        self.assertTrue(any("医院" in text for text in memories), memories)
        self.assertIsNone(self.service.next_extraction_task())

    def test_retrying_failed_writeback_reuses_prepared_result(self) -> None:
        source_id = self.add_source()
        task = self.service.next_extraction_task()
        assert task is not None
        with patch.object(self.db.artifacts, "commit", side_effect=OSError("temporary write failure")):
            first = self.service.commit_extraction(task.source_ids, _payload(source_id))
        self.assertTrue(first.retryable)
        self.assertEqual(len(self.buffer.items), 1)
        # The retry must use the prepared plan, not trust a changed model response.
        second = self.service.commit_extraction(task.source_ids, "not json")
        self.assertEqual(second.written, 1, second.errors)
        self.assertFalse(second.retryable)
        self.assertEqual(len(self.buffer.items), 0)
        self.assertEqual(len(list(self.cache.active("memory"))), 1)

    def test_commit_rejects_consumed_task(self) -> None:
        source_id = self.add_source()
        task = self.service.next_extraction_task()
        assert task is not None
        self.service.commit_extraction(task.source_ids, _payload(source_id))

        again = self.service.commit_extraction(task.source_ids, _payload(source_id))

        self.assertEqual(again.written, 0)
        self.assertIn("task_stale", again.errors)

    def test_commit_rejects_unknown_source_ids(self) -> None:
        self.add_source()
        outcome = self.service.commit_extraction(["missing"], "[]")

        self.assertIn("task_stale", outcome.errors)

    def test_invalid_model_output_keeps_pending_row_retryable(self) -> None:
        source_id = self.add_source()
        task = self.service.next_extraction_task()
        assert task is not None

        with self.assertRaises(ExtractionParseError):
            self.service.commit_extraction(task.source_ids, "not json")

        self.assertEqual([turn.source_id for turn in self.buffer.items], [source_id])
        states = {
            row["source_id"]: row["state"]
            for row in self.db.extraction.pending_extractions()
        }
        self.assertEqual(states.get(source_id), "retrying")
        self.assertIsNone(self.service.next_extraction_task())


class LoopbackEndpointTest(unittest.TestCase):
    """Cover the HTTP mapping of the loopback plan/commit endpoints / 覆盖回环服务端点映射。"""

    def setUp(self) -> None:
        from adapters.loopback.runtime import MemoryService

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.close)
        self.service = MemoryService(Path(self.tmp.name), {"owner_umo": "u1"}, quiet=True)

    def close(self) -> None:
        self.service.store.close()

    def test_plan_returns_prompt_and_commit_dequeues(self) -> None:
        self.service.capture({"text": "我周末要去医院检查眼睛", "speaker": "u1",
                              "role": "user", "at": "2026-10-29T10:00:00"})
        code, plan = self.service.extract_plan({})

        self.assertEqual(code, 200)
        self.assertIn("我周末要去医院检查眼睛", plan["chat_request"]["prompt"])
        self.assertIn("system_prompt", plan["chat_request"])

        code, result = self.service.extract_commit({
            "task_id": plan["task_id"],
            "source_ids": plan["source_ids"],
            "chat_response": {"text": "[]"},
        })
        self.assertEqual(code, 200, result)
        self.assertEqual(result["written"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(self.service.extract_plan({})[0], 204)

    def test_unknown_task_cannot_write_or_consume_another_subject(self) -> None:
        code, captured = self.service.capture({"text": "我周末要去医院检查眼睛", "role": "user"})
        self.assertEqual(code, 200)
        source_id = captured["source_id"]
        code, payload = self.service.extract_commit({
            "task_id": "forged", "source_ids": [source_id],
            "chat_response": {"text": _payload(source_id)},
        })
        self.assertEqual((code, payload["error"]), (409, "task_stale"))
        self.assertEqual(self.service.extract_plan({"subject_key": "different"})[0], 403)
        self.assertEqual(self.service.extract_plan({"subject_key": "u1"})[0], 200)
        self.assertEqual(len(self.service.buffer.items), 1)
        self.assertEqual(list(self.service.cache.active("memory")), [])

    def test_shared_subject_across_hosts_rejects_foreign_subject(self) -> None:
        # Two host clients may use one fixed identity and one database; a
        # different identity must not write, read, or consume their work.
        code, captured = self.service.capture({
            "subject_key": "u1", "text": "我周末要去医院检查眼睛", "role": "user",
            "at": "2026-10-29T10:00:00",
        })
        self.assertEqual(code, 200, captured)
        for method, payload in (
            (self.service.capture, {"subject_key": "u2", "text": "foreign"}),
            (self.service.recall, {"subject_key": "u2", "query": "医院 检查 眼睛"}),
            (self.service.persona, {"subject_key": "u2"}),
            (self.service.extract_plan, {"subject_key": "u2"}),
        ):
            self.assertEqual(method(payload), (403, {"error": "subject_mismatch"}))
        self.assertEqual(len(self.service.buffer.items), 1)
        self.assertEqual(self.service.extract_plan({"subject_key": "u1"})[0], 200)
        # A second client with the same logical subject still sees the task.
        self.assertEqual(self.service.extract_plan({"subject_key": "u1"})[0], 200)
        self.assertEqual(self.service.persona({"subject_key": "u1"})[0], 200)

    def test_default_plan_never_extracts_preexisting_foreign_pending_source(self) -> None:
        # A legacy mixed database may contain foreign pending rows: no-key
        # planning must not consume them for the configured single subject.
        self.service.buffer.add("u2", "other user", "speaker", "foreign-id", "")
        self.assertEqual(self.service.extract_plan({})[0], 204)
        self.assertEqual(self.service.capture({"subject_key": "u1", "text": "my note"})[0], 200)
        code, plan = self.service.extract_plan({})
        self.assertEqual(code, 200)
        self.assertEqual(plan["session_id"], "u1")

    def test_real_commit_recall_observes_artifact(self) -> None:
        code, captured = self.service.capture({"text": "我周末要去医院检查眼睛", "role": "user",
                                                "at": "2026-10-29T10:00:00"})
        self.assertEqual(code, 200)
        code, plan = self.service.extract_plan({"subject_key": "u1"})
        self.assertEqual(code, 200)
        code, result = self.service.extract_commit({
            "task_id": plan["task_id"], "chat_response": {"text": _payload(captured["source_id"])},
        })
        self.assertEqual(code, 200, result)
        self.assertEqual(result["written"], 1)
        code, recall = self.service.recall({"subject_key": "u1", "query": "医院 检查 眼睛"})
        self.assertEqual(code, 200)
        self.assertEqual(recall["items"][0]["id"], result["ids"][0])
        self.assertEqual(self.service.extract_plan({"subject_key": "u1"})[0], 204)

    def test_recall_respects_each_request_budget_after_real_commit(self) -> None:
        code, captured = self.service.capture({"text": "我周末要去医院检查眼睛", "role": "user",
                                                "at": "2026-10-29T10:00:00"})
        self.assertEqual(code, 200)
        _, plan = self.service.extract_plan({"subject_key": "u1"})
        code, result = self.service.extract_commit({
            "task_id": plan["task_id"], "chat_response": {"text": _payload(captured["source_id"])},
        })
        self.assertEqual(code, 200, result)
        query = {"subject_key": "u1", "query": "医院 检查 眼睛"}
        full = self.service.recall({**query, "budget_chars": 600})[1]
        limited = self.service.recall({**query, "budget_chars": 1})[1]
        self.assertGreater(full["chars"], 0)
        self.assertEqual(limited["block"], "")
        self.assertEqual(limited["chars"], 0)
        loose = self.service.recall({**query, "query": "你还记得医院检查眼睛吗", "budget_chars": 20})[1]
        self.assertEqual(loose["block"], "")
        self.assertEqual(loose["items"], [])
        self.assertEqual(self.service.recall({**query, "budget_chars": "invalid"})[0], 400)

    def test_commit_without_task_is_conflict(self) -> None:
        code, payload = self.service.extract_commit({
            "task_id": "gone", "chat_response": {"text": "[]"},
        })

        self.assertEqual(code, 409)
        self.assertEqual(payload["error"], "task_stale")

    def test_invalid_extraction_returns_422(self) -> None:
        self.service.capture({"text": "我周末要去医院检查眼睛", "speaker": "u1",
                              "role": "user", "at": "2026-10-29T10:00:00"})
        _, plan = self.service.extract_plan({})

        code, payload = self.service.extract_commit({
            "task_id": plan["task_id"],
            "source_ids": plan["source_ids"],
            "chat_response": {"text": "not json"},
        })

        self.assertEqual(code, 422)
        self.assertTrue(payload["retryable"])


if __name__ == "__main__":
    unittest.main()
