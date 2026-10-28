"""用真实路由、数据库和业务服务验证 OpenAPI，无需启动 AstrBot。"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
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
WebRoutes = importlib.import_module("_seekmemory_contract.adapters.astrbot.web").WebRoutes
TraceStore = importlib.import_module("_seekmemory_contract.store.run_trace").TraceStore
RunTracer = importlib.import_module("_seekmemory_contract.app.runtime.tracing").RunTracer
ContextBudget = importlib.import_module("_seekmemory_contract.app.budget").ContextBudget


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
            packs=importlib.import_module("_seekmemory_contract.adapters.persona_packs").FilePersonaPacks(ROOT / "persona_seeds", Path(self.temp.name) / "packs"),
            dreams=db.dreams,
        )
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
        )
        transport.json_response = lambda data, status_code=200: SimpleNamespace(
            data=data, status_code=status_code
        )
        transport.error_response = lambda message, status_code=400: SimpleNamespace(
            data={"status": "error", "message": message, "data": None},
            status_code=status_code,
        )
        if body is not None and expected == 200:
            validate_contract(action, body, request=True)
        with patch.dict(sys.modules, {"astrbot.api.web": transport}):
            response = await self.routes.handle(action)
        self.assertEqual(response.status_code, expected)
        data = json.loads(json.dumps(response.data))
        validate_contract(action, data, response.status_code)
        return data

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
        await self.plugin.jobs.close()
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

    async def test_errors_use_actual_status_and_host_envelope(self):
        await self.call("records", username=None, expected=401)
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

    async def test_console_reads_writes_and_guards(self):
        for action in ("graph", "impressions", "dream", "packs", "pack"):
            query = {"reference": "official/big_fish"} if action == "pack" else {}
            await self.call(action, query=query)
            await self.call(action, username=None, query=query, expected=401)
            await self.call(action, method="POST", query=query, expected=405)
        await self.call("packs", query={"collection":"invalid"}, expected=400)
        await self.call("impressions", query={"offset":"bad"}, expected=400)
        await self.call("pack", query={"reference":"mine/../secret"}, expected=400)
        await self.call("pack", query={"reference":"mine/missing"}, expected=404)
        service = self.plugin.services.management_service
        current = service.cache.active("persona")[0]
        command = {"operation":"install", "reference":"official/big_fish",
                   "expectedId":current.header.id, "expectedRevision":current.header.revision,
                   "expectedDigest":service.pack_detail("official/big_fish")["digest"], "confirmed":True}
        await self.call("persona", command, username=None, expected=401)
        await self.call("persona", method="GET", expected=405)
        await self.call("persona", {**command,"confirmed":False}, expected=400)
        await self.call("persona", {**command,"extra":True}, expected=400)
        await self.call("persona", {**command,"expectedDigest":"0" * 64}, expected=409)
        result = await self.call("persona", command)
        self.assertEqual(result["revision"], current.header.revision + 1)
        self.plugin.services.status_service = importlib.import_module("_seekmemory_contract.services.status_service").StatusService(artifacts=self.plugin.store.artifacts,ledger=self.plugin.store.ledger)
        await self.call("status")
        await self.call("persona", command, expected=409)
        seed = service.pack_detail("official/big_fish")["seed"]
        imported = await self.call("persona", {"operation":"import","seed":seed,"confirmed":True})
        await self.call("packs", query={"collection":"mine"})
        await self.call("persona", {"operation":"remove",**imported,"confirmed":True})
        await self.call("task", {"kind":"weekly","confirmed":True})
        await self.call("persona", command, expected=409)
        await self.plugin.jobs.close()
        self.assertEqual(self.plugin.store.sources.recent_sources(since="",limit=100), [])

    async def test_complete_pack_artwork_export_and_install_boundaries(self):
        from persona_pack_fixture import pack
        service = self.plugin.services.management_service
        seed = service.pack_detail("official/big_fish")["seed"]
        complete = pack(seed)
        result = await self.call("persona", {"operation": "importPack", "pack": complete, "confirmed": True})
        reference = result["reference"]
        for action in ("packArtwork", "packExport"):
            await self.call(action, query={"reference": reference})
            await self.call(action, username=None, query={"reference": reference}, expected=401)
            await self.call(action, method="POST", query={"reference": reference}, expected=405)
            await self.call(action, query={"reference": "mine/missing"}, expected=404)
            await self.call(action, query={"reference": "mine/../secret"}, expected=400)
        exported = await self.call("packExport", query={"reference": reference})
        self.assertEqual(exported, complete)
        self.assertEqual(service.pack_artwork(reference), complete["artwork"])
        await self.call("packArtwork", query={"reference": "official/big_fish"}, expected=404)
        await self.call("persona", {"operation": "importPack", "pack": {**complete, "artwork": {"mediaType": "image/png", "dataBase64": "broken"}}, "confirmed": True}, expected=400)
        await self.call("persona", {"operation": "importPack", "pack": complete, "confirmed": False}, expected=400)
        preview = service.pack_detail(reference)
        current = service.cache.active("persona")[0]
        installed = await self.call("persona", {"operation": "install", "reference": reference,
            "expectedId": current.header.id, "expectedRevision": current.header.revision,
            "expectedDigest": preview["digest"], "confirmed": True})
        payload = service.artifacts.get(installed["id"]).payload
        self.assertNotIn("artwork", payload)
        self.assertNotIn("licenseText", payload)
        self.assertEqual(self.plugin.store.sources.recent_sources(since="", limit=100), [])
        await self.call("persona", {"operation": "importPack", "pack": complete, "padding": "x" * (3 * 1024 * 1024), "confirmed": True}, expected=413)

    async def test_persona_rollback_route_preserves_history_and_guards(self):
        service = self.plugin.services.management_service
        seed = service.pack_detail("official/big_fish")["seed"]
        first = service.bootstrap_persona(seed)
        second = service.bootstrap_persona({**seed, "persona": "Changed persona"})
        body = {"id": first["id"], "revision": first["revision"],
                "reason": "Restore reviewed version", "confirmed": True}
        await self.call("rollbackPersona", body, username=None, expected=401)
        await self.call("rollbackPersona", method="GET", expected=405)
        await self.call("rollbackPersona", {**body, "confirmed": False}, expected=400)
        await self.call("rollbackPersona", {**body, "reason": " "}, expected=400)
        await self.call("rollbackPersona", {**body, "revision": 999}, expected=400)
        history = service.artifacts.history(first["id"])
        result = await self.call("rollbackPersona", body)
        self.assertEqual(result["revision"], second["revision"] + 1)
        self.assertEqual(result["restoredRevision"], first["revision"])
        self.assertEqual(service.artifacts.get(first["id"]).payload["text"], seed["persona"])
        self.assertEqual(len(service.artifacts.history(first["id"])), len(history) + 1)
        self.assertTrue(any(row["reason"] == body["reason"] for row in self.plugin.store.ledger.entries()))
        await self.call("task", {"kind": "weekly", "confirmed": True})
        await self.call("rollbackPersona", body, expected=409)
        await self.plugin.jobs.close()

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
        self.assertEqual(len(SPEC["paths"]), 18)
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
