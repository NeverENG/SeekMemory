"""针对 AstrBot 真实请求与插件 API 的可选集成测试。"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT.parents[2]
if (HOST / "astrbot/api/web.py").is_file():
    sys.path.insert(0, str(HOST))
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT / "tests"))
from contract_support import validate_contract  # noqa: E402

try:
    from starlette.requests import Request

    from astrbot.api.web import PluginRequest, bind_request_context

except ImportError:
    Main = None
else:
    Main = importlib.import_module(f"{ROOT.name}.main").Main


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

    async def asyncTearDown(self) -> None:
        await self.plugin.terminate()
        self.temp.cleanup()

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
        self.assertEqual(len(self.plugin._schedulers), 4)
        tasks = list(self.plugin._schedulers)
        await self.plugin.terminate()
        self.assertTrue(all(task.done() for task in tasks))
        self.assertEqual(self.context.registered_web_apis, [])
        self.assertIsNone(self.plugin.db)

    async def test_failed_extraction_preserves_buffer(self) -> None:
        class Provider:
            async def text_chat(self, **_kwargs):
                raise ValueError("private provider detail")

        self.context.provider = Provider()
        self.plugin.buffer.add("bot:FriendMessage:alice", "Remember this plan", "alice")
        with self.assertRaises(ValueError):
            await self.plugin._nightly()
        self.assertEqual(len(self.plugin.buffer.items), 1)
        # DB-backed pending lives in Source + extraction_state, not pending.json.
        self.assertEqual(len(self.plugin.db.pending_extractions()), 1)

    async def test_missing_provider_preserves_daily_quota_and_messages(self) -> None:
        self.plugin.buffer.add("bot:FriendMessage:alice", "Plan A", "alice")
        await self.plugin._nightly()
        self.assertEqual(self.plugin._flush_count, 0)
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
            await self.plugin._nightly()
        self.assertEqual([row.text for row in self.plugin.buffer.items], ["Plan A"])
        self.assertEqual(self.plugin._flush_count, 1)

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
        task = asyncio.create_task(plugin._nightly())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        rows = self.plugin.db.pending_extractions()
        self.assertEqual(sorted(row["text"] for row in rows), ["New plan", "Plan A"])
        self.assertFalse(plugin._flushing)

    async def test_shutdown_flushes_upstream_checkpoint_before_closing_db(self) -> None:
        artifact = importlib.import_module(f"{ROOT.name}.core.artifact")
        store = importlib.import_module(f"{ROOT.name}.store.db")
        art = artifact.make("memory", {"text": "需要保留强化次数", "level": "fact"})
        self.plugin.db.commit(art, expected_revision=0, op="create")
        self.plugin.cache.put(art)
        self.plugin.checkpoint.record(art)
        response = await self.request("status")
        self.assertEqual(json.loads(response.body)["checkpointPending"], 1)
        await self.plugin.terminate()
        db = store.DB(str(Path(self.temp.name) / "memory.db"))
        try:
            saved = db.get(art.header.id)
            self.assertEqual(saved.header.revision, 2)
            self.assertEqual(saved.header.strength.hits, 1)
            self.assertEqual(db.history(art.header.id)[-1]["op"], "reinforce")
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
        await self.plugin._nightly()
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
        await plugin._nightly()
        self.assertEqual(self.context.provider_sessions, ["bot:FriendMessage:alice"])
        self.assertEqual(
            [row.text for row in plugin.buffer.items],
            ["Plan B", "Arrived during model call"],
        )


if __name__ == "__main__":
    unittest.main()
