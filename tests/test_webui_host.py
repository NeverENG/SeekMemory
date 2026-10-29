"""针对 AstrBot 真实请求与插件 API 的可选集成测试。"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT.parents[2]
if (HOST / "astrbot/api/web.py").is_file():
    sys.path.insert(0, str(HOST))
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "tests"))
from contract_support import validate_contract  # noqa: E402

RuntimePackage = importlib.import_module(f"{ROOT.name}.app.runtime")
ActionExecutor = RuntimePackage.ActionExecutor
ActionResult = RuntimePackage.ActionResult

try:
    from starlette.requests import Request

    from astrbot.api.web import PluginRequest, bind_request_context

except ImportError:
    Main = None
else:
    Main = importlib.import_module(f"{ROOT.name}.main").Main


def action_executor_for(sender) -> ActionExecutor:
    class Port:
        async def execute(self, request):
            result = await sender.send(request.session_id, request.text)
            return ActionResult(
                result is not False,
                "" if result is not False else "host_send_failed",
            )

    return ActionExecutor(Port(), None)


class HostContext:
    def __init__(self) -> None:
        self.registered_web_apis = []
        self.provider = None
        self.provider_sessions = []

    def register_web_api(self, route, handler, methods, description) -> None:
        self.registered_web_apis.append((route, handler, methods, description))

    async def get_using_provider_async(self, umo=None):
        self.provider_sessions.append(umo)
        return self.provider


class PrivateEvent:
    """提供捕获和召回所需元数据的私聊宿主事件。"""

    unified_msg_origin = "bot:FriendMessage:u1"

    def __init__(self, text: str, message_id: str = "host-turn") -> None:
        self.message_str = text
        self.message_obj = SimpleNamespace(message_id=message_id)
        self.extras: dict[str, object] = {}

    def get_sender_id(self) -> str:
        return "u1"

    def get_self_id(self) -> str:
        return "bot"

    def is_private_chat(self) -> bool:
        return True

    def get_extra(self, key: str, default: object = None) -> object:
        return self.extras.get(key, default)

    def set_extra(self, key: str, value: object) -> None:
        self.extras[key] = value


@unittest.skipIf(Main is None, "AstrBot host is not installed")
class HostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.context = HostContext()
        self.plugin = Main(
            self.context,
            {
                "db_path": str(Path(self.temp.name) / "memory.db"),
                "max_sessions_per_flush": 1,
            },
        )
        await self.plugin.initialize()

    async def asyncTearDown(self) -> None:
        await self.plugin.terminate()
        self.temp.cleanup()

    async def restart_plugin(self, **config: object) -> None:
        """通过真实生命周期重建依赖配置的服务。"""
        await self.plugin.terminate()
        self.plugin.cfg.update(config)
        await self.plugin.initialize()

    async def request(
        self,
        action: str,
        method: str = "GET",
        body: dict | None = None,
        username: str | None = "admin",
    ):
        """绑定真实宿主请求，不启动消息适配器。

        Args:
            action: 管理接口操作。
            method: HTTP 方法。
            body: 可选 JSON 请求体。
            username: 宿主认证身份；认证失败测试使用 None。

        Returns:
            插件处理器返回的真实 JSON 响应。
        """

        async def receive():
            return {
                "type": "http.request",
                "body": json.dumps(body).encode(),
                "more_body": False,
            }

        raw = Request(
            {
                "type": "http",
                "method": method,
                "path": "/manage/" + action,
                "query_string": b"",
                "headers": [(b"content-type", b"application/json")],
            },
            receive,
        )
        with bind_request_context(PluginRequest(raw, username=username)):
            response = await self.plugin.web.handle(action)
        validate_contract(action, json.loads(response.body), response.status_code)
        return response

    async def test_auth_methods_and_confirmation(self) -> None:
        self.assertEqual(
            (await self.request("records", username=None)).status_code, 401
        )
        self.assertEqual((await self.request("update")).status_code, 405)
        self.assertEqual(
            (await self.request("task", "POST", {"kind": "weekly"})).status_code, 400
        )
        status = await self.request("status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(json.loads(status.body)["ready"])
        malformed = await self.request("task", "POST", {"kind": [], "confirmed": True})
        self.assertEqual(malformed.status_code, 400)

    async def test_provider_lookup_failure_preserves_other_checks(self) -> None:
        async def failing_provider():
            raise ValueError("private provider detail")

        self.context.get_using_provider_async = failing_provider
        response = await self.request("status")
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.body)
        self.assertTrue(result["ready"])
        self.assertFalse(
            next(check for check in result["checks"] if check["name"] == "provider")[
                "ok"
            ]
        )
        self.assertNotIn("private provider detail", response.body.decode())

    async def test_host_discovers_built_page_and_exposes_expected_bridge(self) -> None:
        from astrbot.dashboard.services.plugin_page_service import PluginPageService

        entry = ROOT / "pages/memory/index.html"
        if not entry.exists():
            self.skipTest("Build the dashboard before testing host page discovery")
        service = PluginPageService(SimpleNamespace(plugin_store_path=ROOT.parent))
        metadata = SimpleNamespace(root_dir_name=ROOT.name, reserved=False)
        pages = await service.discover_plugin_pages(metadata)
        self.assertIn("memory", [page.name for page in pages])
        sdk = service.bridge_file.read_text(encoding="utf-8")
        self.assertIn("window.AstrBotPluginPage =", sdk)
        client = (ROOT / "dashboard/src/infrastructure/astrbot-client.ts").read_text(
            encoding="utf-8"
        )
        self.assertIn("window.AstrBotPluginPage", client)

    async def test_initialization_is_idempotent_and_shutdown_owns_resources(
        self,
    ) -> None:
        await self.plugin.initialize()
        await self.plugin.start_jobs()
        expected_schedulers = 5 if self.plugin.services.background_service.dream_enabled else 6
        self.assertEqual(len(self.plugin.services.background_service.tasks), expected_schedulers)
        tasks = list(self.plugin.services.background_service.tasks)
        await self.plugin.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.context.registered_web_apis, [])
        self.assertIsNone(self.plugin.store)

    async def test_concurrent_lifecycle_rebuilds_one_runtime_and_resets_closed_references(self) -> None:
        runtime = self.plugin.services.runtime
        worker = self.plugin.services.runtime_worker
        await asyncio.gather(*(self.plugin.initialize() for _ in range(3)))
        self.assertIs(self.plugin.services.runtime, runtime)
        self.assertIs(self.plugin.services.runtime_worker, worker)
        self.assertIs(worker.runtime, runtime)
        self.assertIs(runtime.action_executor, self.plugin.action_executor)
        tasks = list(self.plugin.services.background_service.tasks)
        await asyncio.gather(self.plugin.terminate(), self.plugin.terminate())
        self.assertTrue(all(task.done() for task in tasks))
        for name in ("services", "store", "buffer", "cache", "jobs", "web", "actions", "run_tracer"):
            self.assertIsNone(getattr(self.plugin, name), name)
        self.assertFalse(self.plugin.ready)
        await asyncio.gather(self.plugin.initialize(), self.plugin.initialize())
        self.assertTrue(self.plugin.ready)
        self.assertIsNot(self.plugin.services.runtime, runtime)
        self.assertIsNot(self.plugin.services.runtime_worker, worker)
        self.assertEqual(len(self.context.registered_web_apis), 1)

    async def test_failed_host_registration_releases_partial_start_and_can_retry(self) -> None:
        await self.plugin.terminate()
        original = self.context.register_web_api

        def broken_registration(*args):
            original(*args)
            raise RuntimeError("private host detail")

        with patch.object(self.context, "register_web_api", side_effect=broken_registration):
            with self.assertRaises(RuntimeError):
                await self.plugin.initialize()
        self.assertFalse(self.plugin.ready)
        self.assertIsNone(self.plugin.services)
        self.assertIsNone(self.plugin.store)
        self.assertEqual(self.context.registered_web_apis, [])
        await self.plugin.initialize()
        self.assertTrue(self.plugin.ready)

    async def test_engine_failure_after_open_does_not_leave_a_live_partial_engine(self) -> None:
        await self.plugin.terminate()
        module = importlib.import_module(f"{ROOT.name}.adapters.astrbot.plugin")
        with patch.object(module.Cache, "load", side_effect=RuntimeError("private storage detail")):
            await self.plugin.initialize()
        self.assertFalse(self.plugin.ready)
        self.assertIsNone(self.plugin.store)
        self.assertIsNone(self.plugin.cache)
        self.assertIsNone(self.plugin.services)
        await self.plugin.initialize()
        self.assertTrue(self.plugin.ready)

    async def test_cleanup_failure_still_releases_other_resources(self) -> None:
        tasks = list(self.plugin.services.background_service.tasks)
        with patch.object(self.plugin.buffer, "save", side_effect=RuntimeError("private buffer detail")):
            await self.plugin.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertIsNone(self.plugin.store)
        self.assertEqual(self.context.registered_web_apis, [])
        await self.plugin.initialize()
        self.assertTrue(self.plugin.ready)

    async def test_cancelled_stop_waits_for_cleanup_before_propagating(self) -> None:
        background = self.plugin.services.background_service
        original = background.stop
        entered, release = asyncio.Event(), asyncio.Event()
        tasks = list(background.tasks)

        async def delayed_stop():
            entered.set()
            await release.wait()
            await original()

        with patch.object(background, "stop", side_effect=delayed_stop):
            stopping = asyncio.create_task(self.plugin.terminate())
            await entered.wait()
            stopping.cancel()
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await stopping
        self.assertTrue(all(task.done() for task in tasks))
        self.assertIsNone(self.plugin.store)
        self.assertIsNone(self.plugin.services)

    async def test_late_host_callbacks_after_stop_are_ignored_without_stale_access(self) -> None:
        event = PrivateEvent("remember this", "stopped-turn")
        await self.restart_plugin(owner_umo=event.unified_msg_origin)
        await self.plugin.buffer_message(event)
        await self.plugin.terminate()
        extras = dict(event.extras)
        await self.plugin.observe_agent_begin(event, None)
        await self.plugin.observe_agent_done(event, None, SimpleNamespace(role="err"))
        await self.plugin.observe_tool(event, SimpleNamespace(name="memory_search"), {"query": "private"})
        await self.plugin.observe_tool_result(event, SimpleNamespace(name="memory_search"), {}, "private result")
        await self.plugin.buffer_message(event)
        await self.plugin.capture_reply(event, SimpleNamespace(completion_text="late reply"))
        await self.plugin.record_delivery(event)
        await self.plugin.attention_gate(event)
        self.assertEqual(event.extras, extras)
        self.assertIsNone(self.plugin.services)
        await self.plugin.initialize()
        rows = self.plugin.store.sources.recent_sources(since="", limit=10)
        self.assertEqual([row.role for row in rows], ["user"])

    async def test_failed_extraction_preserves_buffer(self) -> None:
        class Provider:
            async def text_chat(self, **_kwargs):
                raise ValueError("private provider detail")

        self.context.provider = Provider()
        self.plugin.buffer.add("bot:FriendMessage:alice", "Remember this plan", "alice")
        with self.assertRaises(ValueError):
            await self.plugin.services.background_service.nightly()
        self.assertEqual(len(self.plugin.buffer.items), 1)
        # Store-backed pending lives in Source + extraction_state, not pending.json.
        self.assertEqual(len(self.plugin.store.extraction.pending_extractions()), 1)

    async def test_missing_provider_preserves_daily_quota_and_messages(self) -> None:
        self.plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        await self.plugin.services.background_service.nightly()
        self.assertEqual(self.plugin.services.ingest_service.flush_count, 0)
        self.assertEqual(len(self.plugin.buffer.items), 1)

    async def test_failed_session_does_not_block_other_ready_sessions(self) -> None:
        class Provider:
            async def text_chat(self, **kwargs):
                if "Plan A" in kwargs["prompt"]:
                    raise ValueError("private model failure")
                return SimpleNamespace(completion_text="[]")

        self.context.provider = Provider()
        self.plugin.cfg["max_sessions_per_flush"] = 2
        self.plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        self.plugin.buffer.add("bot:FriendMessage:bob", "Plan B", "bob")
        with self.assertRaises(ValueError):
            await self.plugin.services.background_service.nightly()
        self.assertEqual([row.text for row in self.plugin.buffer.items], ["Plan A"])
        self.assertEqual(self.plugin.services.ingest_service.flush_count, 1)

    async def test_cancellation_preserves_inflight_and_new_messages(self) -> None:
        started = asyncio.Event()
        plugin = self.plugin

        class Provider:
            async def text_chat(self, **_kwargs):
                plugin.buffer.add("bot:FriendMessage:alice", "New plan", "alice")
                started.set()
                await asyncio.Event().wait()

        self.context.provider = Provider()
        plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        task = asyncio.create_task(plugin.services.background_service.nightly())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        rows = self.plugin.store.extraction.pending_extractions()
        self.assertEqual(sorted(row["text"] for row in rows), ["New plan", "Plan A"])
        self.assertFalse(plugin.services.ingest_service.flushing)

    async def test_runtime_observe_is_default_and_gate_is_opt_in(self) -> None:
        class Event:
            unified_msg_origin = "bot:GroupMessage:g1"
            message_str = "ambient message"
            message_obj = SimpleNamespace(message_id="m1")

            def __init__(self):
                self.extras = {}
                self.call_llm = True

            def is_private_chat(self):
                return False

            def get_sender_id(self):
                return "u1"

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

            def should_call_llm(self, value):
                self.call_llm = value

        observe_event = Event()
        await self.plugin.buffer_message(observe_event)
        self.assertTrue(observe_event.call_llm)
        self.assertEqual(observe_event.extras["_seekmemory_runtime_action"], "observe")
        self.assertEqual(
            self.plugin.services.runtime.store.get(observe_event.unified_msg_origin).wait_until,
            0.0,
        )

        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.services.runtime.wait_seconds = 0
        self.plugin.services.runtime.clear_wait(observe_event.unified_msg_origin)
        gated_event = Event()
        await self.plugin.buffer_message(gated_event)
        self.assertFalse(gated_event.call_llm)
        self.assertEqual(gated_event.extras["_seekmemory_runtime_action"], "observe")

    async def test_persona_status_exposes_revision_timeline(self) -> None:
        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        first = artifact.make("persona", {"text": "first persona"})
        self.plugin.store.artifacts.commit(first, expected_revision=0, op="promote")
        second = artifact.revise(first, payload={"text": "second persona"})
        self.plugin.store.artifacts.commit(second, expected_revision=1, op="promote")
        timeline = self.plugin.services.status_service.persona()
        self.assertIsNotNone(timeline)
        self.assertEqual(timeline["id"], first.header.id)
        self.assertEqual(timeline["text"], "second persona")
        self.assertEqual([row["revision"] for row in timeline["revisions"]], [1, 2])

    async def test_persona_history_uses_each_versions_own_evidence(self) -> None:
        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        first = artifact.make("persona", {"text": "first"},
                              lineage=artifact.Lineage(sources=("s1",), derived_from=("i1",)))
        self.plugin.store.artifacts.commit(first, expected_revision=0, op="promote")
        second = artifact.revise(first, payload={"text": "second"},
                                  lineage=artifact.Lineage(sources=("s1", "s2"), derived_from=("i1", "i2")))
        self.plugin.store.artifacts.commit(second, expected_revision=1, op="promote")
        timeline = self.plugin.services.status_service.persona()
        self.assertEqual(timeline["revisions"][0]["sourceIds"], ["s1"])
        self.assertEqual(timeline["revisions"][1]["sourceIds"], ["s1", "s2"])
        self.assertEqual(timeline["revisions"][0]["derivedFrom"], ["i1"])
        self.assertEqual(self.plugin.services.status_service.header_evidence("invalid"), ([], []))
        self.assertEqual(self.plugin.services.status_service.header_evidence({}), ([], []))
        self.assertNotIn("sources", timeline)

    async def test_capture_to_extraction_to_weekly_persona_uses_real_pairs(self) -> None:
        await self.restart_plugin(open_to="everyone")
        self.plugin.context.provider_sessions.clear()
        for i in range(3):
            event = PrivateEvent("事情很多，有点难过", f"persona-turn-{i}")
            await self.plugin.buffer_message(event)
            await self.plugin.capture_reply(event, SimpleNamespace(role="assistant", completion_text="听起来你很难过，先缓缓"))
        self.assertEqual(self.plugin.context.provider_sessions, [])
        pending = self.plugin.store.extraction.pending_extractions()
        self.assertEqual(len(pending), 6)
        for row in pending:
            if row["role"] == "assistant":
                parent = next(r for r in pending if r["source_id"] == row["reply_to"])
                self.assertEqual(row["topic_id"], parent["topic_id"])
        class Provider:
            async def text_chat(inner, **kwargs):
                rows = self.plugin.store.extraction.pending_extractions()
                selected = [r for r in rows if f'[{r["source_id"]}]' in kwargs["prompt"]]
                results = []
                for row in selected:
                    if row["role"] == "assistant":
                        results.append({"text": "她回应情绪", "level": "scene", "bot_behavior": "respond_emotion",
                                        "confidence": 0.95, "evidence_source_ids": [row["reply_to"], row["source_id"]]})
                return SimpleNamespace(completion_text=json.dumps(results))
        self.context.provider = Provider()
        while self.plugin.buffer.items:
            await self.plugin.services.background_service.flush("test")
        calls = len(self.context.provider_sessions)
        await self.plugin.services.background_service.weekly()
        self.assertEqual(len(self.context.provider_sessions), calls)
        persona, = self.plugin.cache.active("persona")
        self.assertEqual(persona.header.subject_id, "bot:self")
        self.assertEqual(len(persona.header.lineage.sources), 6)
        block, info = self.plugin.services.recall_service.build(
            "你好", "bot:FriendMessage:stranger", True, "stranger"
        )
        self.assertIn(persona.header.id, info["final_ids"])
        self.assertIn("你先回应情绪", block)

    async def test_inject_memory_preserves_context_contract(self) -> None:
        await self.restart_plugin(open_to="everyone")
        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        text = "周末去青川公园散步"
        event = PrivateEvent(text)
        source = source_module.Source(
            id="context-source", turn_id="context-turn",
            session_id=event.unified_msg_origin, speaker_id="u1", role="user",
            text=text, at="2026-01-01T00:00:00",
        )
        self.plugin.store.sources.append_sources([source])
        memory = artifact.make(
            "memory", {"text": text, "level": "fact"}, subject_id="u1",
            lineage=artifact.Lineage(sources=(source.id,)),
        )
        self.plugin.store.artifacts.commit(
            memory, expected_revision=0, op="create", source_ids=(source.id,)
        )
        self.plugin.cache.put(memory)
        req = SimpleNamespace(system_prompt="base")
        await self.plugin.inject_memory(event, req)

        self.assertEqual(event.get_extra("_seekmemory_recall_ids"), (memory.header.id,))
        self.assertTrue(req.system_prompt.startswith("base"))
        self.assertIn(text, req.system_prompt)
        journal_event = next(
            row for row in reversed(self.plugin.journal.events)
            if row["kind"] == "recall" and row["stage"] == "assemble"
        )
        self.assertEqual(journal_event["status"], "info")
        self.assertEqual(journal_event["context"]["picked"], 1)
        self.assertGreater(journal_event["context"]["chars"], 0)
        self.assertEqual(self.plugin.services.capacity_service.context_chars,
                         journal_event["context"]["chars"])
        with open(self.plugin._calls_path(), encoding="utf-8") as stream:
            logged = json.loads(stream.readlines()[-1])
        self.assertEqual(
            (logged["kind"], logged["mode"], logged["picked"], logged["chars"]),
            ("FriendMessage", journal_event["context"]["mode"], 1,
             journal_event["context"]["chars"]),
        )
        self.assertNotIn(text, json.dumps(logged, ensure_ascii=False))

        empty_event = PrivateEvent("现在几点了")
        empty_req = SimpleNamespace(system_prompt="base")
        await self.plugin.inject_memory(empty_event, empty_req)
        self.assertEqual(empty_req.system_prompt, "base")
        self.assertEqual(empty_event.get_extra("_seekmemory_recall_ids"), ())
        self.assertEqual(self.plugin.services.capacity_service.context_chars, 0)

    async def test_inject_memory_fails_open_without_leaking_error_detail(self) -> None:
        await self.restart_plugin(open_to="everyone")

        class FailedMemoryContext:
            def build_context(self, request):
                raise RuntimeError(f"db path /secret: {request.query}")

        self.plugin.services.runtime.memory_context = FailedMemoryContext()
        event = PrivateEvent("private message body")
        req = SimpleNamespace(system_prompt="base")
        hooks = importlib.import_module(f"{ROOT.name}.adapters.astrbot.hooks")
        with patch.object(hooks.logger, "error") as error_log:
            await self.plugin.inject_memory(event, req)

        self.assertEqual(req.system_prompt, "base")
        self.assertIsNone(event.get_extra("_seekmemory_recall_ids"))
        journal_event = self.plugin.journal.events[-1]
        self.assertEqual(
            (journal_event["kind"], journal_event["status"]), ("recall", "failed")
        )
        self.assertEqual(journal_event["error"]["type"], "RuntimeError")
        serialized = json.dumps(journal_event)
        self.assertNotIn("private message body", serialized)
        self.assertNotIn("/secret", serialized)
        logged = " ".join(str(call.args[0]) for call in error_log.call_args_list)
        self.assertNotIn("/secret", logged)
        self.assertNotIn("private message body", logged)
        self.assertIn("RuntimeError", logged)

    async def test_default_access_rejects_unconfigured_private_chat(self) -> None:
        event = PrivateEvent("private message body")
        req = SimpleNamespace(system_prompt="base")
        await self.plugin.buffer_message(event)
        await self.plugin.capture_reply(
            event, SimpleNamespace(role="assistant", completion_text="private reply")
        )
        await self.plugin.inject_memory(event, req)

        self.assertEqual(req.system_prompt, "base")
        self.assertIsNone(event.get_extra("_seekmemory_recall_ids"))
        self.assertEqual(self.plugin.store.extraction.pending_extractions(), [])
        self.assertIsNone(self.plugin.store.sources.latest_user_source(event.unified_msg_origin))
        self.assertFalse(any(row["kind"] == "recall" for row in self.plugin.journal.events))

    async def test_normal_source_failure_keeps_host_delivery_correlated(self) -> None:
        await self.restart_plugin(open_to="everyone")
        event = PrivateEvent("first", "partial-source")
        await self.plugin.buffer_message(event)
        with patch.object(self.plugin.store.sources, "append_sources", side_effect=OSError("busy")):
            await self.plugin.capture_reply(
                event, SimpleNamespace(role="assistant", completion_text="reply"),
            )
            assistant_id = event.get_extra("_seekmemory_assistant_source_id")
            self.assertTrue(assistant_id)
            await self.plugin.record_delivery(event)
            state = self.plugin.services.runtime.store.get(event.unified_msg_origin)
            self.assertEqual(state.unread_count, 0)
        self.plugin.services.runtime.retry_writebacks()
        self.assertIn(assistant_id, self.plugin.store.sources.sources_by_ids([assistant_id]))
        rows = self.plugin.store.runtime_episodes.list(event.unified_msg_origin)
        delivered = [row for row in rows if row["run_id"] and row["decision"] != "action"]
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["assistant_source_id"], assistant_id)

    async def test_normal_delivery_acknowledges_its_event_without_clearing_new_input(self) -> None:
        await self.restart_plugin(open_to="everyone")
        first = PrivateEvent("first", "delivery-first")
        second = PrivateEvent("second", "delivery-second")
        third = PrivateEvent("third", "delivery-third")
        await self.plugin.buffer_message(first)
        await self.plugin.buffer_message(second)
        self.assertEqual(first.get_extra("_seekmemory_read_through_seq"), 1)
        self.assertEqual(second.get_extra("_seekmemory_read_through_seq"), 2)
        await self.plugin.capture_reply(
            first, SimpleNamespace(role="assistant", completion_text="first reply"),
        )
        await self.plugin.record_delivery(first)
        state = self.plugin.services.runtime.store.get(first.unified_msg_origin)
        self.assertEqual(state.read_through_seq, 1)
        self.assertEqual(state.unread_count, 1)
        await self.plugin.capture_reply(
            second, SimpleNamespace(role="assistant", completion_text="second reply"),
        )
        await self.plugin.record_delivery(second)
        await self.plugin.buffer_message(third)
        await self.plugin.record_delivery(first)
        state = self.plugin.services.runtime.store.get(first.unified_msg_origin)
        self.assertEqual(state.read_through_seq, 2)
        self.assertEqual(state.unread_count, 1)
        episodes = self.plugin.store.runtime_episodes.list(first.unified_msg_origin)
        self.assertEqual(len(episodes), 2)

    async def test_old_processed_parent_uses_utc8_view_without_rewriting_evidence(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:legacy-parent"
        original_at = "2026-10-27T15:00:00+00:00"
        self.plugin.store.sources.append_sources([source_module.Source(
            "old-user", "old-turn", session_id, "u1", "user", "旧消息", original_at,
        )])
        self.plugin.buffer.add(
            session_id, "新回复", "bot", "new-reply", "2026-10-27T15:00:05+00:00",
            turn_id="old-turn", reply_to="old-user", role="assistant",
        )
        # Restart/chunk boundaries may leave only the reply in pending input.
        self.plugin.buffer.reload()

        class Model:
            async def complete(self, request):
                return SimpleNamespace(text=json.dumps([{
                    "level": "fact", "text": "有证据的结论",
                    "evidence_source_ids": ["old-user", "new-reply"],
                }]))

        outcome = await self.plugin.services.ingest_service.extract(
            list(self.plugin.buffer.items), Model(),
        )
        self.assertFalse(outcome.retryable, outcome.errors)
        self.assertEqual(outcome.written, 1)
        saved = self.plugin.store.sources.sources_by_ids(["old-user"])["old-user"]
        self.assertEqual(saved.at, original_at)

    async def test_deferred_wait_dispatches_once(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-defer"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        src = source_module.Source(
            id="src-defer", turn_id="turn-defer", session_id=session_id,
            speaker_id="u1", role="user", text="ambient deferred message",
            at="2026-01-01T00:00:00",
        )
        self.plugin.store.sources.append_sources([src])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now
        self.plugin.services.runtime.store.put(state)

        class Provider:
            def __init__(self):
                self.calls = []

            async def text_chat(self, prompt, system_prompt=None):
                self.calls.append((prompt, system_prompt))
                return SimpleNamespace(completion_text="deferred reply")

        class Actions:
            def __init__(self):
                self.sent = []

            async def send(self, session, text):
                self.sent.append((session, text))

        provider = Provider()

        async def provider_for(session):
            return provider

        actions = Actions()
        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.services.runtime.action_executor = action_executor_for(actions)
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        self.assertEqual(provider.calls[0][0], "ambient deferred message")
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        self.assertEqual(actions.sent, [(session_id, "deferred reply")])
        rows = self.plugin.store.runtime_episodes.list(session_id)
        self.assertEqual(rows[0]["reason"], "deferred_wait")
        self.assertTrue(rows[0]["assistant_source_id"])
        self.assertTrue(rows[0]["run_id"])
        self.assertEqual(self.plugin.services.runtime.store.get(session_id).wait_until, 0.0)
        source_row = self.plugin.store.conn.execute(
            "SELECT role FROM sources WHERE id = ?", (rows[0]["assistant_source_id"],)
        ).fetchone()
        self.assertEqual(source_row["role"], "assistant")
        self.assertTrue(any(
            turn.role == "assistant" and turn.text == "deferred reply"
            for turn in self.plugin.buffer.items
        ))

    async def test_runtime_gate_off_never_dispatches_deferred(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-gate-off"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = False
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-gate-off", turn_id="turn-gate-off", session_id=session_id,
            speaker_id="u1", role="user", text="must stay deferred",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now + 120
        self.plugin.services.runtime.store.put(state)

        class Provider:
            def __init__(self):
                self.calls = 0

            async def text_chat(self, prompt, system_prompt=None):
                self.calls += 1
                return SimpleNamespace(completion_text="must not send")

        class Actions:
            def __init__(self):
                self.sent = []

            async def send(self, session, text):
                self.sent.append((session, text))

        provider = Provider()
        actions = Actions()

        async def provider_for(session):
            return provider

        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.services.runtime.action_executor = action_executor_for(actions)
        await self.plugin.services.runtime_worker.tick()
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        self.assertEqual(provider.calls, 0)
        self.assertEqual(actions.sent, [])
        self.assertGreater(self.plugin.services.runtime.store.get(session_id).wait_until, now)

    async def test_missing_source_keeps_future_deferred_wait(self) -> None:
        session_id = "bot:GroupMessage:g-missing-source"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now + 120
        self.plugin.services.runtime.store.put(state)
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        self.assertEqual(
            self.plugin.services.runtime.store.get(session_id).wait_until, now + 120
        )

    async def test_runtime_retry_only_state_dispatches(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-retry-only"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-retry-only", turn_id="turn-retry-only", session_id=session_id,
            speaker_id="u1", role="user", text="retry-only input",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = 0.0
        state.next_retry_at = now - 1
        self.plugin.services.runtime.store.put(state)

        class Provider:
            async def text_chat(self, prompt, system_prompt=None):
                return SimpleNamespace(completion_text="retry-only reply")

        class Actions:
            def __init__(self):
                self.sent = []

            async def send(self, session, text):
                self.sent.append((session, text))

        async def provider_for(session):
            return Provider()

        actions = Actions()
        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.services.runtime.action_executor = action_executor_for(actions)
        await self.plugin.services.runtime_worker.tick()
        self.assertEqual(actions.sent, [(session_id, "retry-only reply")])

    async def test_runtime_tick_dedupes_deferred_dispatch(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-tick-defer"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-tick", turn_id="turn-tick", session_id=session_id,
            speaker_id="u1", role="user", text="tick deferred",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now
        self.plugin.services.runtime.store.put(state)

        class Provider:
            async def text_chat(self, prompt, system_prompt=None):
                return SimpleNamespace(completion_text="tick reply")

        class Actions:
            def __init__(self):
                self.sent = []

            async def send(self, session, text):
                self.sent.append((session, text))

        async def provider_for(session):
            return Provider()

        actions = Actions()
        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.services.runtime.action_executor = action_executor_for(actions)
        await self.plugin.services.runtime_worker.tick()
        await self.plugin.services.runtime_worker.tick()
        self.assertEqual(actions.sent, [(session_id, "tick reply")])

    async def test_deferred_provider_failure_schedules_retry_and_is_private(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-provider-fail"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-fail", turn_id="turn-fail", session_id=session_id,
            speaker_id="u1", role="user", text="secret provider input",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now
        self.plugin.services.runtime.store.put(state)

        async def provider_for(session):
            raise RuntimeError("provider leaked secret")

        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.trace.rows.clear()
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        state = self.plugin.services.runtime.store.get(session_id)
        self.assertGreater(state.wait_until, now)
        self.assertGreater(state.next_retry_at, now)
        rows = self.plugin.store.runtime_episodes.list(session_id)
        self.assertEqual(rows[0]["outcome"], "error")
        self.assertNotIn("secret", json.dumps([row.context for row in self.plugin.trace.rows]))

    async def test_deferred_send_failure_schedules_retry(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-send-fail"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-send-fail", turn_id="turn-send-fail", session_id=session_id,
            speaker_id="u1", role="user", text="send failure input",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now
        self.plugin.services.runtime.store.put(state)

        class Provider:
            async def text_chat(self, prompt, system_prompt=None):
                return SimpleNamespace(completion_text="will fail")

        class Actions:
            async def send(self, session, text):
                return False

        async def provider_for(session):
            return Provider()

        self.plugin.context.get_using_provider_async = provider_for
        self.plugin.services.runtime.action_executor = action_executor_for(Actions())
        await self.plugin.services.runtime_worker.dispatch(session_id, now)
        state = self.plugin.services.runtime.store.get(session_id)
        self.assertGreater(state.wait_until, now)
        self.assertGreater(state.next_retry_at, now)
        rows = self.plugin.store.runtime_episodes.list(session_id)
        self.assertEqual(rows[0]["outcome"], "error")
        self.assertEqual(rows[0]["error"], "RuntimeError")

    async def test_deferred_retry_exhaustion_enters_dead_state(self) -> None:
        source_module = importlib.import_module(f"{ROOT.name}.core.source")
        session_id = "bot:GroupMessage:g-retry-dead"
        now = time.time()
        self.plugin.cfg["runtime_gate_enabled"] = True
        self.plugin.store.sources.append_sources([source_module.Source(
            id="src-retry", turn_id="turn-retry", session_id=session_id,
            speaker_id="u1", role="user", text="retry me",
            at="2026-01-01T00:00:00",
        )])
        state = self.plugin.services.runtime.store.get(session_id)
        state.wait_until = now
        self.plugin.services.runtime.store.put(state)

        async def provider_for(session):
            raise RuntimeError("fail once")

        self.plugin.context.get_using_provider_async = provider_for
        for _ in range(4):
            state = self.plugin.services.runtime.store.get(session_id)
            await self.plugin.services.runtime_worker.dispatch(session_id, state.wait_until or now)
        state = self.plugin.services.runtime.store.get(session_id)
        self.assertEqual(state.wait_until, 0.0)
        self.assertEqual(state.next_retry_at, 0.0)
        self.assertEqual(state.last_reason, "dispatch_dead")
        self.assertEqual(state.dispatch_attempts, 3)
        rows = self.plugin.store.runtime_episodes.list(session_id)
        self.assertEqual(len(rows), 3)

    async def test_tool_filter_is_opt_in(self) -> None:
        class ToolSet:
            def __init__(self):
                self.tools = [SimpleNamespace(name="shell_exec")]
                self.removed = []

            def remove_tool(self, name):
                self.removed.append(name)
                self.tools = []

        class Event:
            unified_msg_origin = "bot:GroupMessage:g-tool"
            message_str = "hello"

            def __init__(self):
                self.extras = {}

            def is_private_chat(self):
                return False

            def get_sender_id(self):
                return "u1"

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        tools = ToolSet()
        req = SimpleNamespace(system_prompt="", func_tool=tools)
        self.plugin.cfg["runtime_tool_filter_enabled"] = False
        await self.plugin.inject_memory(Event(), req)
        self.assertEqual(tools.removed, [])
        self.assertEqual([tool.name for tool in tools.tools], ["shell_exec"])

    async def test_reinforcement_waits_for_successful_response(self) -> None:
        from types import SimpleNamespace

        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        art = artifact.make(
            "memory",
            {"text": "shared recall phrase", "level": "fact"},
            scope="shared",
            subject_id="u1",
        )
        self.plugin.store.artifacts.commit(art, expected_revision=0, op="create")
        self.plugin.cache.put(art)

        class Event:
            unified_msg_origin = "bot:GroupMessage:g1"
            message_str = "shared recall phrase"

            def __init__(self):
                self.extras = {}

            def is_private_chat(self):
                return False

            def get_sender_id(self):
                return "u1"

            def get_self_id(self):
                return "bot"

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        class ToolSet:
            def __init__(self):
                self.tools = [
                    SimpleNamespace(name="memory_search"),
                    SimpleNamespace(name="shell_exec"),
                ]
                self.removed = []

            def remove_tool(self, name):
                self.removed.append(name)
                self.tools = [tool for tool in self.tools if tool.name != name]

        tools = ToolSet()
        self.plugin.cfg["runtime_tool_filter_enabled"] = True
        event = Event()
        await self.plugin.observe_agent_begin(event, None)
        req = SimpleNamespace(system_prompt="", func_tool=tools)
        await self.plugin.inject_memory(event, req)
        self.assertEqual(tools.removed, ["shell_exec"])
        self.assertEqual([tool.name for tool in tools.tools], ["memory_search"])
        self.assertTrue(event.get_extra("_seekmemory_recall_ids"))
        self.assertEqual(self.plugin.checkpoint.pending(), 0)
        await self.plugin.capture_reply(
            event, SimpleNamespace(role="assistant", completion_text="ok")
        )
        self.assertEqual(self.plugin.checkpoint.pending(), 1)
        pending = self.plugin.store.extraction.pending_extractions()
        self.assertTrue(any(
            row["role"] == "assistant" and row["text"] == "ok" for row in pending
        ))
        await self.plugin.record_delivery(event)
        await self.plugin.observe_agent_done(event, None, SimpleNamespace(role="assistant"))
        trace = self.plugin.run_traces.snapshot()
        self.assertEqual(len(trace["runs"]), 1)
        self.assertTrue(trace["runs"][0]["delivered"])
        self.assertEqual([row["event"] for row in trace["events"]], [
            "agent_begin", "llm_request", "llm_response", "message_sent", "agent_done"
        ])
        self.assertNotIn("shared recall phrase", json.dumps(trace))
        episodes = self.plugin.store.runtime_episodes.list("bot:GroupMessage:g1")
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["delivered"], 1)
        self.assertEqual(episodes[0]["run_id"], trace["runs"][0]["id"])
        self.assertNotIn("text", episodes[0])

        failure_event = Event()
        await self.plugin.observe_agent_done(
            failure_event, None, SimpleNamespace(role="err")
        )
        failures = self.plugin.store.runtime_episodes.list("bot:GroupMessage:g1")
        self.assertEqual(len(failures), 2)
        self.assertEqual(failures[0]["outcome"], "error")

    async def test_shutdown_flushes_upstream_checkpoint_before_closing_db(self) -> None:
        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        store = importlib.import_module(f"{ROOT.name}.store")
        art = artifact.make("memory", {"text": "需要保留强化次数", "level": "fact"})
        self.plugin.store.artifacts.commit(art, expected_revision=0, op="create")
        self.plugin.cache.put(art)
        self.plugin.checkpoint.record(art)
        response = await self.request("status")
        self.assertEqual(json.loads(response.body)["checkpointPending"], 1)
        await self.plugin.terminate()
        db = store.open_store(str(Path(self.temp.name) / "memory.db"))
        try:
            saved = db.artifacts.get(art.header.id)
            self.assertEqual(saved.header.revision, 2)
            self.assertEqual(saved.header.strength.hits, 1)
            self.assertEqual(db.artifacts.history(art.header.id)[-1]["op"], "reinforce")
        finally:
            db.close()

    async def test_topics_are_extracted_separately_and_status_counts_turns(
        self,
    ) -> None:
        prompts = []

        class Provider:
            async def text_chat(self, **kwargs):
                prompts.append(kwargs["prompt"])
                return SimpleNamespace(completion_text="[]")

        self.context.provider = Provider()
        self.plugin.cfg["max_sessions_per_flush"] = 2
        self.plugin.buffer.add("bot:FriendMessage:alice", "Travel itinerary", "alice")
        self.plugin.buffer.add("bot:FriendMessage:alice", "Database index", "alice")
        self.assertEqual(len(self.plugin.buffer.topics()), 2)
        response = await self.request("status")
        self.assertEqual(
            json.loads(response.body)["pending"],
            [{"session": "bot:FriendMessage:alice", "count": 2}],
        )
        await self.plugin.services.background_service.nightly()
        self.assertEqual(len(prompts), 2)
        self.assertTrue(
            all(
                not ("Travel itinerary" in p and "Database index" in p) for p in prompts
            )
        )
        self.assertEqual(self.plugin.buffer.items, [])
        events = [
            e for e in self.plugin.journal.events if e["stage"] == "topic.extract"
        ]
        self.assertEqual(len({e["context"]["topic"] for e in events}), 2)

    async def test_session_cap_and_new_messages_survive_success(self) -> None:
        plugin = self.plugin

        class Provider:
            async def text_chat(self, **_kwargs):
                plugin.buffer.add(
                    "bot:FriendMessage:alice", "Arrived during model call", "alice"
                )
                return SimpleNamespace(completion_text="[]")

        self.context.provider = Provider()
        plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        plugin.buffer.add("bot:FriendMessage:bob", "Plan B", "bob")
        await plugin.services.background_service.nightly()
        self.assertEqual(self.context.provider_sessions, ["bot:FriendMessage:alice"])
        self.assertEqual(
            [row.text for row in plugin.buffer.items],
            ["Plan B", "Arrived during model call"],
        )


if __name__ == "__main__":
    unittest.main()
