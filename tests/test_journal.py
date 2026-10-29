"""业务日志行为、任务关联和兼容性测试。"""

from __future__ import annotations

import asyncio
import ast
import inspect
import json
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contracts import DialogueTurn
from tests.absorb_support import absorb
from store import open_store
from webui.jobs import Jobs
from webui.journal import Journal


class JournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.jsonl"
        self.journal = Journal(self.path)

    async def test_extraction_stages_report_real_module_and_keep_payload_private(
        self,
    ) -> None:
        db = open_store(str(Path(self.temp.name) / "memory.db"))
        self.addCleanup(db.close)
        provider = SimpleNamespace(
            text_chat=AsyncMock(
                return_value=SimpleNamespace(
                    completion_text='[{"level":"fact","text":"PRIVATE OUTPUT","about":"other"}]'
                )
            )
        )
        written = await absorb(
            [DialogueTurn("demo:FriendMessage:1", "1", "user", "PRIVATE INPUT")],
            db.artifacts,
            db.sources,
            None,
            None,
            provider,
            stage=partial(self.journal.span, "extract"),
            strict=True,
        )
        self.assertEqual(written.written, 1)
        stages = {e["stage"] for e in self.journal.events}
        self.assertTrue(
            {
                "provider.call",
                "response.parse",
                "memory.deduplicate",
                "artifact.validate",
                "artifact.persist",
            }
            <= stages
        )
        owners = {
            "provider.call": "services/ingest_service.py",
            "artifact.persist": "services/ingest_service.py",
            "response.parse": "perceive/absorb.py",
            "memory.deduplicate": "perceive/absorb.py",
            "artifact.validate": "perceive/absorb.py",
        }
        for stage, relative in owners.items():
            events = [event for event in self.journal.events if event["stage"] == stage]
            self.assertTrue(events)
            tree = ast.parse((Path(__file__).resolve().parents[1] / relative).read_text(encoding="utf-8"))
            for event in events:
                source = event["source"]
                self.assertEqual(source["file"], relative)
                functions = [node for node in ast.walk(tree)
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and node.lineno <= source["line"] <= node.end_lineno]
                self.assertTrue(functions)
                owner = min(functions, key=lambda node: node.end_lineno - node.lineno)
                self.assertEqual(source["function"], owner.name)
        self.assertNotIn("PRIVATE", self.path.read_text(encoding="utf-8"))

    def test_direct_and_callback_locations(self) -> None:
        expected_line = inspect.currentframe().f_lineno + 1
        self.journal.record("test", "info", "Direct event")
        source = self.journal.events[-1]["source"]
        self.assertEqual(source["file"], "tests/test_journal.py")
        self.assertEqual(source["function"], "test_direct_and_callback_locations")
        self.assertEqual(source["line"], expected_line)
        callback = partial(self.journal.record, "extract", "warning")
        expected_line = inspect.currentframe().f_lineno + 1
        callback("Artifact validation failed: ValueError")
        self.assertEqual(self.journal.events[-1]["source"]["line"], expected_line)
        self.assertEqual(self.journal.events[-1]["level"], "WARNING")

    def test_transparent_diagnostic_wrappers_keep_business_locations(self) -> None:
        from services.diagnostics import diagnostic, span

        expected = inspect.currentframe().f_lineno + 1
        diagnostic(self.journal.record, "test", "info", "Wrapped diagnostic")
        self.assertEqual(self.journal.events[-1]["source"]["line"], expected)
        self.assertEqual(self.journal.events[-1]["source"]["file"], "tests/test_journal.py")
        expected = inspect.currentframe().f_lineno + 1
        with span(self.journal.span, "test", "wrapped"):
            pass
        for event in list(self.journal.events)[-2:]:
            self.assertEqual(event["source"]["file"], "tests/test_journal.py")
            self.assertEqual(event["source"]["line"], expected)

    async def test_stage_context_inherits_task_and_resets(self) -> None:
        jobs = Jobs(self.journal)

        async def operation() -> None:
            with self.journal.span("extract", "session.extract", messages=3) as metrics:
                await asyncio.sleep(0)
                metrics["written"] = 2

        task_id = jobs.submit("extract", operation)
        await jobs.task
        events = list(self.journal.events)
        self.assertTrue(all(e["taskId"] == task_id for e in events))
        stage = next(e for e in events if e["stage"] and e["status"] == "succeeded")
        self.assertEqual(stage["context"], {"messages": 3, "written": 2})
        self.assertGreaterEqual(stage["durationMs"], 0)
        self.assertEqual(stage["source"]["function"], "operation")
        self.journal.record("recall", "info", "Unrelated event")
        self.assertEqual(self.journal.events[-1]["taskId"], "")
        # 阶段完成不能使遗留任务在重启时被误判为完成。
        self.journal.record("extract", "running", "Task started", "orphan")
        self.journal.record(
            "extract", "succeeded", "Stage completed", "orphan", stage="parse"
        )
        restored = Journal(self.path)
        self.assertEqual(restored.events[-1]["status"], "interrupted")
        self.assertEqual(restored.events[-1]["taskId"], "orphan")

    def test_stage_failure_preserves_exception_without_payload(self) -> None:
        failure = ValueError("SECRET TOKEN AND MODEL RESPONSE")
        with self.assertRaises(ValueError) as caught:
            with self.journal.span("edit", "artifact.revise", artifactId="artifact-1"):
                raise failure
        self.assertIs(caught.exception, failure)
        event = self.journal.events[-1]
        self.assertEqual(event["error"]["type"], "ValueError")
        self.assertEqual(
            event["error"]["frames"][-1]["function"],
            "test_stage_failure_preserves_exception_without_payload",
        )
        text = self.path.read_text(encoding="utf-8")
        self.assertNotIn("SECRET", text)
        self.assertNotIn(str(Path.cwd()), text)

    async def test_stage_cancellation_and_task_isolation(self) -> None:
        started = asyncio.Event()
        jobs = Jobs(self.journal)

        async def operation() -> None:
            with self.journal.span("extract", "provider.call"):
                started.set()
                await asyncio.Event().wait()

        jobs.submit("extract", operation)
        await started.wait()
        self.journal.record("diagnose", "info", "Concurrent request")
        self.assertEqual(self.journal.events[-1]["taskId"], "")
        await jobs.close()
        stages = [e for e in self.journal.events if e["stage"]]
        self.assertEqual(stages[-1]["status"], "cancelled")

    def test_legacy_events_and_persistence_failure(self) -> None:
        old = {
            "id": "old",
            "at": "2026-10-21",
            "kind": "plugin",
            "status": "ready",
            "message": "Legacy",
            "taskId": "",
        }
        self.path.write_text(json.dumps(old) + "\n", encoding="utf-8")
        restored = Journal(self.path)
        self.assertEqual(restored.events[0], old)
        with patch.object(Path, "open", side_effect=OSError("disk full")):
            restored.record("edit", "info", "Still visible")
        self.assertTrue(restored.persistence_error)
        self.assertEqual(restored.events[-1]["message"], "Still visible")


if __name__ == "__main__":
    unittest.main()
