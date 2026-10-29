"""Production composition path for the AstrBot runtime worker."""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

# Importing the composition module must not require a live AstrBot install.
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("seekmemory-test")


class _HostStar:
    def __init__(self, context, config):
        pass


api.star = SimpleNamespace(Context=object, Star=_HostStar)
event = types.ModuleType("astrbot.api.event")
event.AstrMessageEvent = object
event.filter = SimpleNamespace(
    EventMessageType=SimpleNamespace(ALL="all")
)
core = types.ModuleType("astrbot.core")
utils = types.ModuleType("astrbot.core.utils")
utils_path = types.ModuleType("astrbot.core.utils.astrbot_path")
utils_path.get_astrbot_plugin_data_path = lambda: str(ROOT / "data")
sys.modules.update({
    "astrbot": astrbot,
    "astrbot.api": api,
    "astrbot.api.event": event,
    "astrbot.core": core,
    "astrbot.core.utils": utils,
    "astrbot.core.utils.astrbot_path": utils_path,
})

import importlib  # noqa: E402
AstrBotPlugin = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.plugin"
).AstrBotPlugin
AstrBotHooks = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.hooks"
).AstrBotHooks
AttentionHooks = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.attention"
).AttentionHooks
RuntimePackage = importlib.import_module(f"{ROOT.name}.app.runtime")
ToolPolicy = RuntimePackage.ToolPolicy
ActionStatus = RuntimePackage.ActionStatus


class _Sources:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def latest_user_source(self, session_id):
        self.calls.append(session_id)
        return self.row


class AttentionHookDelegationTest(unittest.TestCase):
    def test_hooks_expose_only_declared_host_dependencies(self) -> None:
        host = SimpleNamespace(unrelated_resource=object(), clock=lambda: 1.0)
        for hook in (AstrBotHooks(host), AttentionHooks(host)):
            self.assertIs(hook._bindings, host)
            with self.assertRaises(AttributeError):
                _ = hook.unrelated_resource

    def test_registration_exports_keep_plugin_callback_metadata(self) -> None:
        domain = importlib.import_module(f"{ROOT.name}.adapters.astrbot.domain")
        registration = importlib.import_module(f"{ROOT.name}.adapters.astrbot.registration")
        hooks = importlib.import_module(f"{ROOT.name}.adapters.astrbot.hooks")
        self.assertIs(domain.build_astrbot_hooks, hooks.build_astrbot_hooks)
        self.assertIs(domain.build_astrbot_hooks, registration.build_astrbot_hooks)
        original_filter = registration.filter
        decorator = lambda *_args, **_kwargs: lambda function: function
        registration.filter = SimpleNamespace(
            EventMessageType=SimpleNamespace(ALL="all"),
            **{name: decorator for name in (
                "on_llm_request", "event_message_type", "on_llm_response", "after_message_sent",
                "on_agent_begin", "on_agent_done", "on_using_llm_tool", "on_llm_tool_respond",
                "on_astrbot_loaded",
            )},
        )
        try:
            callbacks = domain.build_astrbot_hooks("seekmemory_test_plugin.main")
        finally:
            registration.filter = original_filter
        self.assertEqual(list(callbacks), [
            "inject_memory", "buffer_message", "capture_reply", "record_delivery",
            "observe_agent_begin", "observe_agent_done", "observe_tool", "observe_tool_result",
            "start_jobs", "attention_gate",
        ])
        for name, callback in callbacks.items():
            self.assertEqual(callback.__name__, name)
            self.assertEqual(callback.__module__, "seekmemory_test_plugin.main")
            self.assertEqual(callback.__qualname__, "Main." + name)

    def test_may_observe_falls_back_to_host_hooks(self) -> None:
        calls = []

        class Hooks:
            def _may_observe(self, event):
                calls.append(event)
                return True

        host = SimpleNamespace(hooks=Hooks())
        attention = AttentionHooks(host)
        event = object()
        self.assertTrue(attention._may_observe(event))
        self.assertEqual(calls, [event])


class RuntimePluginContextTest(unittest.TestCase):
    def test_plugin_uses_explicit_host_composition(self):
        self.assertNotIn(AstrBotHooks, AstrBotPlugin.__mro__)
        self.assertNotIn(AttentionHooks, AstrBotPlugin.__mro__)

    def test_make_run_context_maps_source_event_and_receipt_time(self):
        plugin = object.__new__(AstrBotPlugin)
        plugin._self_id = "bot-1"
        plugin.store = SimpleNamespace(
            sources=_Sources({
                "id": "s1",
                "text": "hello",
                "at": "1970-01-01T00:00:10+00:00",
            })
        )

        context = plugin._make_run_context("umo:1", 123.5)

        self.assertEqual(context.session_id, "umo:1")
        self.assertEqual(context.text, "hello")
        self.assertEqual(context.source_id, "s1")
        self.assertEqual(context.bot_id, "bot-1")
        self.assertEqual(context.event_time, 10.0)
        self.assertEqual(context.received_at, 123.5)


class ConsoleLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise production composition against a minimal host boundary."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = SimpleNamespace(registered_web_apis=[])

        async def provider(umo=None):
            return None

        def register(*route):
            self.context.registered_web_apis.append(route)

        self.context.get_using_provider_async = provider
        self.context.register_web_api = register
        self.web_module = patch.dict(sys.modules, {
            "astrbot.api.web": types.ModuleType("astrbot.api.web"),
        })
        self.web_module.start()
        self.addCleanup(self.web_module.stop)
        self.plugin = AstrBotPlugin(self.context, {
            "db_path": str(Path(self.temp.name) / "memory.db"),
        })
        self.addAsyncCleanup(self.plugin.stop)

    async def test_restart_preserves_console_packs_and_dream_history(self):
        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        self.assertEqual(len(self.context.registered_web_apis), 1)
        before = self.plugin.services.management_service.pack_catalog()
        self.assertGreater(len(before["items"]), 0)
        self.plugin.store.dreams.begin("2026-10-28")
        self.plugin.store.dreams.finish("2026-10-28", status="done", summary={})
        history = self.plugin.services.management_service.dream_journal()
        self.assertEqual(len(history["items"]), 1)

        await self.plugin.stop()
        self.assertFalse(self.plugin.ready)
        self.assertEqual(self.context.registered_web_apis, [])
        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        self.assertEqual(len(self.context.registered_web_apis), 1)
        management = self.plugin.services.management_service
        self.assertEqual(management.pack_catalog(), before)
        self.assertEqual(management.dream_journal(), history)

    async def test_registration_failure_allows_retry_with_console_services(self):
        with patch.object(self.context, "register_web_api", side_effect=RuntimeError("host unavailable")):
            with self.assertRaises(RuntimeError):
                await self.plugin.start()
        self.assertFalse(self.plugin.ready)
        self.assertIsNone(self.plugin.store)
        self.assertEqual(self.context.registered_web_apis, [])

        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        management = self.plugin.services.management_service
        self.assertGreater(len(management.pack_catalog()["items"]), 0)
        self.assertEqual(management.dream_journal()["items"], [])
        self.assertEqual(len(self.context.registered_web_apis), 1)


class HostHookActionTest(unittest.TestCase):
    def test_schedule_proactive_delegates_to_runtime_when_enabled(self):
        calls = []

        class Runtime:
            def schedule_proactive(self, session_id, delay, *, now):
                calls.append((session_id, delay))

        hook = AstrBotHooks()
        hook.services = SimpleNamespace(runtime=Runtime())
        hook._c = lambda key, default: True if key == "proactive_enabled" else default
        hook._schedule_proactive("s1")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "s1")
        self.assertEqual(calls[0][1], 1800.0)

    def test_send_action_audit_has_attempt_and_terminal(self):
        class Ledger:
            def __init__(self):
                self.finished = []

            def begin(self, request, **kwargs):
                return SimpleNamespace(action_id="send-action")

            def finish(self, record, status, **kwargs):
                self.finished.append((record.action_id, status))

        class ExtraEvent:
            def __init__(self):
                self.extras = {}

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        hook = AstrBotHooks()
        hook.action_executor = Ledger()
        event = ExtraEvent()
        hook._begin_send_action(event, "s1", "run-1", "turn-1")
        self.assertIsNotNone(event.get_extra("_seekmemory_send_action"))
        hook._finish_send_action(event, ActionStatus.SUCCEEDED)
        self.assertEqual(hook.action_executor.finished, [("send-action", ActionStatus.SUCCEEDED)])

    def test_tool_hooks_use_action_ledger_without_payload(self):
        class Ledger:
            def __init__(self):
                self.started = []
                self.finished = []

            def begin(self, request, **kwargs):
                self.started.append((request, kwargs))
                return SimpleNamespace(action_id="action-1")

            def finish(self, record, status, **kwargs):
                self.finished.append((record.action_id, status, kwargs))

        class Tracer:
            def run_id(self, event):
                return "run-1"

            def tool_begin(self, event, tool):
                pass

            def tool_end(self, event, tool):
                pass

        class Trace:
            def record(self, *args, **kwargs):
                pass

        class Event:
            unified_msg_origin = "umo:1"
            extras = {}

            def get_sender_id(self):
                return "sender-1"

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        hook = AstrBotHooks()
        hook.ready = True
        hook.services = SimpleNamespace(
            access_service=SimpleNamespace(
                may_observe=lambda session, sender: True,
                may_recall=lambda session, sender: True,
            )
        )
        hook.run_tracer = Tracer()
        hook.trace = Trace()
        hook.tool_policy = ToolPolicy(("memory_",))
        hook.action_executor = Ledger()
        event = Event()
        tool = SimpleNamespace(name="memory_search", id="call-1")
        asyncio.run(hook.observe_tool(event, tool, {"query": "private"}))
        self.assertEqual(len(hook.action_executor.started), 1)
        self.assertNotIn("private", str(hook.action_executor.started[0]))
        asyncio.run(
            hook.observe_tool_result(
                event, tool, {}, SimpleNamespace(status="ok")
            )
        )
        self.assertEqual(len(hook.action_executor.finished), 1)
        self.assertEqual(hook.action_executor.finished[0][1].value, "succeeded")


if __name__ == "__main__":
    unittest.main()
