"""用真实路由、数据库和业务服务验证 OpenAPI，无需启动 AstrBot。"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

from jsonschema import Draft202012Validator, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_support import ROOT, SAMPLES, SPEC, validate_contract  # noqa: E402

# 独立命名空间支持业务模块的相对导入，不导入依赖宿主的 main.py。
package = ModuleType("_seekmemory_contract")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
artifact = importlib.import_module("_seekmemory_contract.core.artifact")
store_module = importlib.import_module("_seekmemory_contract.store")
Store = store_module.Store
open_store = store_module.open_store
Cache = importlib.import_module("_seekmemory_contract.store.cache").Cache
Graph = importlib.import_module("_seekmemory_contract.core.graph").Graph
HybridRetriever = importlib.import_module("_seekmemory_contract.recall.retriever").HybridRetriever
RecallService = importlib.import_module("_seekmemory_contract.services.recall_service").RecallService
ManagementService = importlib.import_module("_seekmemory_contract.services.management_service").ManagementService
Journal = importlib.import_module("_seekmemory_contract.webui.journal").Journal
Jobs = importlib.import_module("_seekmemory_contract.webui.jobs").Jobs
Buffer = importlib.import_module("_seekmemory_contract.perceive.buffer").Buffer
WebRoutes = importlib.import_module("_seekmemory_contract.webui.routes").WebRoutes
TraceStore = importlib.import_module("_seekmemory_contract.store.run_trace").TraceStore
RunTracer = importlib.import_module("_seekmemory_contract.app.runtime.tracing").RunTracer
ContextBudget = importlib.import_module("_seekmemory_contract.app.budget").ContextBudget
ImportService = importlib.import_module("_seekmemory_contract.services.import_service").ImportService
ImportFileStore = importlib.import_module("_seekmemory_contract.webui.import_files").ImportFileStore
ChatLabReader = importlib.import_module("_seekmemory_contract.adapters.chatlab").ChatLabReader
RoleSelection = importlib.import_module(
    "_seekmemory_contract.services.import_policy"
).RoleSelection


class ApiContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_reports_source_recall_budget_and_rejects_invalid_values(
        self,
    ) -> None:
        self.plugin.budget = ContextBudget(
            source_recall_enabled=False,
            source_recall_hours=48,
            source_recall_max_candidates=9,
        )
        result = await self.call("status")
        self.assertEqual(result["budget"], self.plugin.budget.as_dict())
        for change in (
            {"source_recall_enabled": "false"},
            {"source_recall_hours": 0},
            {"source_recall_max_candidates": -1},
        ):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                validate_contract(
                    "status", {**result, "budget": {**result["budget"], **change}}
                )

    async def test_status_topics_exposes_counts_and_times_without_message_text(
        self,
    ) -> None:
        self.plugin.buffer.add(
            "bot:FriendMessage:alice", "另一话题", "alice", at="invalid"
        )
        result = await self.routes._status()
        validate_contract("status", result)
        self.assertEqual(sum(item["count"] for item in result["pendingTopics"]), 2)
        self.assertEqual(len(result["pendingTopics"]), 2)
        self.assertIsNotNone(result["pendingTopics"][0]["oldestAt"])
        self.assertIsNone(result["pendingTopics"][1]["oldestAt"])
        self.assertEqual(
            result["extractionPolicy"],
            {
                "backlogThreshold": 30,
                "topicTtlSeconds": 86400.0,
                "maxTopicsPerBatch": 6,
            },
        )
        self.assertIsNone(result["checkpointPending"])
        self.assertNotIn("契约测试消息", json.dumps(result, ensure_ascii=False))
        self.plugin.cfg["topic_ttl_seconds"] = 0
        self.plugin._c = self.plugin.cfg.get
        self.assertEqual(
            (await self.routes._status())["extractionPolicy"]["topicTtlSeconds"], 0
        )

    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        journal = Journal(Path(self.temp.name) / "lifecycle.jsonl")
        jobs = Jobs(journal)
        self.addAsyncCleanup(jobs.close)
        self.plugin = SimpleNamespace(
            ready=True,
            store=db,
            cache=cache,
            graph=Graph(db.artifacts),
            journal=journal,
            jobs=jobs,
            cfg={},
            _c={}.get,
            buffer=Buffer(),
            checkpoint=None,
            budget=ContextBudget(),
            context=SimpleNamespace(
                get_using_provider_async=AsyncMock(return_value=None)
            ),
            services=SimpleNamespace(
                background_service=SimpleNamespace(
                    tasks=[],
                    nightly=asyncio.Event().wait,
                    weekly=asyncio.Event().wait,
                ),
                capacity_service=SimpleNamespace(status=lambda: {
                    "state": "normal",
                    "actions": [],
                    "reasons": [],
                    "pressure": 0.0,
                    "snapshot": {
                        "sourceRows": 0,
                        "sourceBytes": 0,
                        "pendingRows": 0,
                        "deferredRows": 0,
                        "deadRows": 0,
                        "databaseBytes": 0,
                        "artifactCount": 0,
                        "artifactBytes": 0,
                        "contextChars": 0,
                        "traceRows": 0,
                    },
                    "queue": {},
                }),
                status_service=SimpleNamespace(
                    persona=lambda: None, ledger_valid=lambda: True
                ),
            ),
        )
        self.plugin.hybrid_retriever = HybridRetriever(self.plugin.graph, cache)
        self.plugin.services.recall_service = RecallService(
            cache=cache,
            graph=self.plugin.graph,
            artifacts=db.artifacts,
            sources=db.sources,
            budget=self.plugin.budget,
            config={}.get,
            owner_umo=lambda: "",
            hybrid_retriever=self.plugin.hybrid_retriever,
        )
        self.plugin.services.management_service = ManagementService(
            artifacts=db.artifacts,
            sources=db.sources,
            ledger=db.ledger,
            cache=cache,
            recall_service=self.plugin.services.recall_service,
        )
        self.plugin.import_files = ImportFileStore(Path(self.temp.name) / "imports")
        self.plugin.services.import_service = ImportService(
            imports=db.imports,
            extraction=db.extraction,
            ingest=SimpleNamespace(),
            maintenance=SimpleNamespace(),
            files=self.plugin.import_files,
            reader=ChatLabReader(),
            provider_for=AsyncMock(return_value=None),
            journal=journal,
            logger=logging.getLogger("test.import"),
        )
        self.plugin.services.import_service.run = AsyncMock(return_value=None)
        self.plugin.active_import_task_id = ""
        self.plugin.active_import_started_task_id = ""
        self.plugin.run_traces = TraceStore(Path(self.temp.name) / "runs.jsonl")
        self.plugin.buffer.add(
            "bot:FriendMessage:alice",
            "契约测试消息",
            "alice",
            at="2026-10-21T12:00:00+08:00",
        )
        self.routes = WebRoutes(self.plugin)
        self.ids = []
        for index, (family, payload) in enumerate(
            [
                *(
                    ("memory", {"text": "中文咖啡偏好", "level": level})
                    for level in ("fact", "scene", "detail", "impression")
                ),
                ("persona", {"text": "耐心"}),
                ("example", {"user": "你好", "assistant": "你好呀"}),
                (
                    "media",
                    {"type": "web", "title": "文章", "url": "https://example.com"},
                ),
                ("secret", {"ref": "private-ref", "shadow_text": "一个承诺"}),
                ("designated", {"text": "归还咖啡计划", "trigger": "咖啡"}),
            ]
        ):
            art = artifact.make(
                family,
                {**payload, "owner_umo": "bot:FriendMessage:alice"},
                scope=("private", "shared", "shadow")[index % 3],
            )
            db.artifacts.upsert(art)
            cache.put(art)
            self.ids.append(art.header.id)
        self.command = {
            "id": self.ids[0],
            "expectedRevision": 1,
            "payload": {
                "text": "新的咖啡偏好",
                "level": "fact",
                "owner_umo": "bot:FriendMessage:alice",
            },
            "state": "active",
            "scope": "private",
            "reason": "纠正",
            "confirmed": True,
        }

    async def call(
        self,
        action,
        body=None,
        *,
        method=None,
        username="admin",
        query=None,
        expected=200,
        files=None,
    ):
        """仅替代宿主传输边界，执行真实处理器并验证响应。

        Args:
            action: 操作名称。
            body: JSON 请求体。
            method: 可选 HTTP 方法覆盖，用于验证 405。
            username: 宿主认证身份。
            query: 查询参数。
            expected: 预期 HTTP 状态码。

        Returns:
            真实处理器输出的 JSON 数据。
        """
        transport = ModuleType("astrbot.api.web")
        transport.request = SimpleNamespace(
            username=username,
            method=method or ("POST" if body is not None else "GET"),
            query=query or {},
            body=AsyncMock(return_value=json.dumps(body).encode()),
            json=AsyncMock(return_value=body),
            files=AsyncMock(return_value=files or {}),
        )
        transport.json_response = lambda data, status_code=200: SimpleNamespace(
            data=data, status_code=status_code
        )
        transport.error_response = lambda message, status_code=400: SimpleNamespace(
            data={"status": "error", "message": message, "data": None},
            status_code=status_code,
        )
        if body is not None and expected == 200 and action != "importUpload":
            validate_contract(action, body, request=True)
        with patch.dict(sys.modules, {"astrbot.api.web": transport}):
            response = await self.routes.handle(action)
        self.assertEqual(response.status_code, expected)
        data = json.loads(json.dumps(response.data))
        validate_contract(action, data, response.status_code)
        return data

    class Upload:
        filename = "history.json"
        size = None

        async def save(self, path):
            path.write_text(json.dumps({
                "chatlab": {"version": "0.0.2"},
                "meta": {"name": "private", "platform": "qq", "type": "private"},
                "members": [
                    {"platformId": "bot-1", "accountName": "Bot"},
                    {"platformId": "user-1", "accountName": "User"},
                ],
                "messages": [
                    {"platformMessageId": "m-user", "sender": "user-1", "timestamp": 1700000000, "content": "Hello"},
                    {"platformMessageId": "m-bot", "sender": "bot-1", "timestamp": 1700000001, "content": "Hi"},
                ],
            }), encoding="utf-8")

    async def test_all_operations_and_legacy_logs(self):
        records = await self.call("records")
        self.assertEqual(len(records["records"]), 9)
        for node_id in self.ids:
            await self.call("detail", query={"id": node_id})
        await self.call("status")
        await self.call("update", self.command)
        await self.call("detail", query={"id": self.ids[0]})
        await self.call(
            "update", {**self.command, "expectedRevision": 2, "state": "forgotten"}
        )
        await self.call("records")
        before = self.plugin.store.conn.total_changes
        await self.call(
            "diagnose",
            {"query": "咖啡", "umo": "bot:FriendMessage:alice", "speaker": "alice"},
        )
        self.assertEqual(before, self.plugin.store.conn.total_changes)
        task = await self.call("task", {"kind": "extract", "confirmed": True})
        await asyncio.sleep(0)
        await self.call("status")
        await self.call("cancel", {**task, "confirmed": True})
        if self.plugin.jobs.task is not None:
            await asyncio.gather(self.plugin.jobs.task, return_exceptions=True)
        self.plugin.journal.events.append(
            {
                "id": "legacy",
                "at": "",
                "kind": "plugin",
                "status": "ready",
                "message": "旧日志",
                "taskId": "",
            }
        )
        await self.call("events")
        await self.call("events", query={"kind": "extract", "search": task["id"]})
        upload = await self.call(
            "importUpload",
            method="POST",
            files={"file": self.Upload()},
        )
        role = {
            "stageKey": upload["stageKey"],
            "botPlatformId": "bot-1",
            "targetPlatformId": "user-1",
            "targetUmo": "qq:FriendMessage:user-1",
            "botMemberId": "bot-1",
            "targetMemberId": "user-1",
        }
        preview = await self.call("importValidate", role)
        self.assertEqual(preview["preview"]["uniqueSourceCount"], 2)
        imported = await self.call("importConfirm", {**role, "confirmed": True})
        await asyncio.sleep(0)
        self.assertNotIn("targetUmo", json.dumps(await self.call("importTasks")))
        await self.call("importTask", query={"id": imported["id"]})

        # A recoverable task retains its file and private role mapping for retry.
        self.plugin.store.imports.finish_task(
            imported["id"], "failed", persona_status="not_run", retain_stage=True
        )
        retry = await self.call("importRetry", {"id": imported["id"], "confirmed": True})
        if self.plugin.jobs.task is not None:
            await asyncio.gather(self.plugin.jobs.task, return_exceptions=True)
        self.plugin.store.imports.finish_task(
            retry["id"], "failed", persona_status="not_run", retain_stage=True
        )
        await self.call("importTask", query={"id": retry["id"]})
        await self.call("importAbandon", {"id": retry["id"], "confirmed": True})
        await self.call("importTasks")

        cancel_id = "hi_cancel_api_contract"
        self.plugin.store.imports.create_task(cancel_id, "stage-unused")
        self.plugin.store.imports.set_status(cancel_id, "running")
        self.plugin.jobs.task = asyncio.create_task(asyncio.Event().wait())
        self.plugin.jobs.kind = "history_import"
        self.plugin.active_import_task_id = cancel_id
        await self.call("importCancel", {"id": cancel_id, "confirmed": True})
        await asyncio.gather(self.plugin.jobs.task, return_exceptions=True)
        self.plugin.jobs.task = None
        self.plugin.jobs.kind = ""
        self.plugin.active_import_task_id = ""
        self.plugin.store.imports.finish_task(cancel_id, "cancelled", persona_status="not_run")
        await self.plugin.jobs.close()

    async def test_errors_use_actual_status_and_host_envelope(self):
        await self.call("records", username=None, expected=401)
        await self.call("importTasks", username=None, expected=401)
        await self.call("importTask", username=None, query={"id": "missing"}, expected=401)
        await self.call("importUpload", username=None, method="POST", expected=401)
        await self.call(
            "importValidate", {"stageKey": "missing"}, username=None, expected=401
        )
        await self.call(
            "importConfirm", {"confirmed": True}, username=None, expected=401
        )
        await self.call(
            "importCancel", {"id": "missing", "confirmed": True},
            username=None, expected=401
        )
        await self.call(
            "importRetry", {"id": "missing", "confirmed": True},
            username=None, expected=401
        )
        await self.call(
            "importAbandon", {"id": "missing", "confirmed": True},
            username=None, expected=401
        )
        await self.call("update", method="GET", expected=405)
        await self.call("detail", query={"id": "missing"}, expected=404)
        await self.call("update", {**self.command, "confirmed": False}, expected=400)
        await self.call(
            "update", {**self.command, "expectedRevision": 99}, expected=409
        )
        await self.call("update", {**self.command, "reason": "x" * 70000}, expected=413)
        await self.call(
            "diagnose", {"query": "", "umo": "x", "speaker": "x"}, expected=400
        )
        await self.call("task", {"kind": "unknown", "confirmed": True}, expected=400)
        await self.call("cancel", {"id": "missing", "confirmed": True}, expected=409)
        await self.call("task", {"kind": "weekly", "confirmed": True})
        await self.call("task", {"kind": "extract", "confirmed": True}, expected=409)
        await self.call("update", self.command, expected=409)
        await self.plugin.jobs.close()
        with patch.object(self.plugin.store.artifacts, "list", side_effect=OSError("private error")):
            await self.call("records", expected=500)
        self.plugin.ready = False
        await self.call("records", expected=503)
        await self.call("status")
        await self.call("events")

    async def test_concurrent_import_retries_are_serialized(self):
        service = self.plugin.services.import_service
        staged = await self.plugin.import_files.save_upload(self.Upload())
        selection = RoleSelection(
            bot_platform_id="bot-1",
            target_platform_id="user-1",
            target_umo="qq:FriendMessage:user-1",
            bot_member_id="bot-1",
            target_member_id="user-1",
        )
        await service.validate_stage(staged.key, selection)
        old_task_id = service.create_task(staged.key, selection)
        self.plugin.store.imports.finish_task(
            old_task_id, "failed", persona_status="not_run", retain_stage=True
        )

        validation_started = asyncio.Event()
        allow_validation = asyncio.Event()
        run_started = asyncio.Event()
        allow_run = asyncio.Event()
        validation_calls = 0
        original_validate = service.validator.validate_stage

        async def delayed_validate(*args, **kwargs):
            nonlocal validation_calls
            validation_calls += 1
            validation_started.set()
            await allow_validation.wait()
            return await original_validate(*args, **kwargs)

        async def hold_run(_task_id, _selection):
            run_started.set()
            await allow_run.wait()

        service.validator.validate_stage = delayed_validate
        service.run = hold_run
        body = {"id": old_task_id, "confirmed": True}
        transport = ModuleType("astrbot.api.web")
        transport.request = SimpleNamespace(
            username="admin",
            method="POST",
            query={},
            body=AsyncMock(return_value=json.dumps(body).encode()),
            json=AsyncMock(return_value=body),
            files=AsyncMock(return_value={}),
        )
        transport.json_response = lambda data, status_code=200: SimpleNamespace(
            data=data, status_code=status_code
        )
        transport.error_response = lambda message, status_code=400: SimpleNamespace(
            data={"status": "error", "message": message, "data": None},
            status_code=status_code,
        )
        try:
            with patch.dict(sys.modules, {"astrbot.api.web": transport}):
                first = asyncio.create_task(self.routes.handle("importRetry"))
                await validation_started.wait()
                second = asyncio.create_task(self.routes.handle("importRetry"))
                await asyncio.sleep(0)
                allow_validation.set()
                responses = await asyncio.gather(first, second)
                await run_started.wait()

            self.assertEqual(
                sorted(response.status_code for response in responses), [200, 409]
            )
            self.assertEqual(validation_calls, 1)
            task_rows = self.plugin.store.conn.execute(
                "SELECT COUNT(*) FROM history_import_tasks"
            ).fetchone()[0]
            self.assertEqual(task_rows, 2)
        finally:
            allow_validation.set()
            allow_run.set()
            if self.plugin.jobs.task is not None:
                await asyncio.gather(self.plugin.jobs.task, return_exceptions=True)

    async def test_cancel_before_import_runner_starts_terminalizes_task(self):
        service = self.plugin.services.import_service
        staged = await self.plugin.import_files.save_upload(self.Upload())
        selection = RoleSelection(
            bot_platform_id="bot-1",
            target_platform_id="user-1",
            target_umo="qq:FriendMessage:user-1",
            bot_member_id="bot-1",
            target_member_id="user-1",
        )
        await service.validate_stage(staged.key, selection)
        runner_started = asyncio.Event()

        async def run_import(*_args):
            runner_started.set()
            await asyncio.Event().wait()

        service.run = AsyncMock(side_effect=run_import)
        confirmation = await self.call(
            "importConfirm",
            {
                "stageKey": staged.key,
                "botPlatformId": selection.bot_platform_id,
                "targetPlatformId": selection.target_platform_id,
                "targetUmo": selection.target_umo,
                "botMemberId": selection.bot_member_id,
                "targetMemberId": selection.target_member_id,
                "confirmed": True,
            },
        )
        task_id = confirmation["id"]
        result = await self.call("importCancel", {"id": task_id, "confirmed": True})
        await asyncio.gather(self.plugin.jobs.task, return_exceptions=True)

        task = service.task(task_id)
        self.assertEqual(result["id"], task_id)
        self.assertFalse(runner_started.is_set())
        self.assertEqual(task["status"], "cancelled")
        self.assertFalse(task["can_retry"])
        from _seekmemory_contract.webui.import_files import ImportFileError

        with self.assertRaises(ImportFileError):
            service.files.path_for_key(staged.key)
        self.plugin.jobs.task = None
        self.plugin.jobs.kind = ""
        self.plugin.active_import_task_id = ""
        self.plugin.active_import_started_task_id = ""

    async def test_trace_auth_filter_and_content_exclusion(self):
        extras = {}
        event = SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)
        tracer = RunTracer(self.plugin.run_traces)
        tracer.begin(event)
        tracer.request(event, {"mode": "strict", "final_ids": [self.ids[0]],
                               "query": "NEVER_PERSIST_THIS"})
        tracer.done(event, "ok")
        result = await self.call("traces")
        self.assertEqual(len(result["runs"]), 1)
        self.assertFalse(result["runs"][0]["delivered"])
        self.assertNotIn("NEVER_PERSIST_THIS", json.dumps(result))
        filtered = await self.call("traces", query={"state": "not_recalled"})
        self.assertEqual(filtered["runs"], [])
        await self.call("traces", username="", expected=401)
        await self.call("traces", method="POST", expected=405)
        await self.call("traces", query={"state": "invalid"}, expected=400)

    async def test_trimmed_text_limits_match_request_contract(self):
        query = {
            "query": " " * 4500 + "咖啡" + " " * 4500,
            "umo": "bot:FriendMessage:alice",
            "speaker": "alice",
        }
        await self.call("diagnose", query)
        for value in (" " * 20, "x" * 4001):
            bad = {**query, "query": value}
            with self.assertRaises(ValidationError):
                validate_contract("diagnose", bad, request=True)
            await self.call("diagnose", bad, expected=400)
        await self.call("update", {**self.command, "reason": " " * 400 + "纠正"})

    async def test_contract_rejects_mutated_shapes_and_requests(self):
        for schema in SPEC["components"]["schemas"].values():
            Draft202012Validator.check_schema(schema)
        self.assertEqual(len(SPEC["paths"]), 17)
        result = await self.call("status")
        for bad in ({**result, "ready": "yes"}, {**result, "schedulerCount": -1}):
            with self.assertRaises(ValidationError):
                validate_contract("status", bad)
        for change in ({"confirmed": False}, {"expectedRevision": 0}, {"extra": True}):
            bad = {**self.command, **change}
            with self.assertRaises(ValidationError):
                validate_contract("update", bad, request=True)
            await self.call(
                "update", bad, expected=400 if "expectedRevision" not in change else 409
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", type=Path)
    args, rest = parser.parse_known_args()
    result = unittest.main(argv=[sys.argv[0], *rest], exit=False).result
    if result.wasSuccessful() and args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        args.export.write_text(
            json.dumps(SAMPLES, ensure_ascii=False), encoding="utf-8"
        )
    sys.exit(0 if result.wasSuccessful() else 1)
