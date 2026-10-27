"""Tests for the adapter bridging AgentRuntime to the recall pipeline."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.seekmemory_context import SeekMemoryContextAdapter  # noqa: E402
from app.runtime import (  # noqa: E402
    AgentRuntime,
    InMemoryStateStore,
    MemoryContext,
    MemoryContextRequest,
    RuntimeInput,
)


class SeekMemoryContextAdapterTest(unittest.TestCase):
    def test_delegates_event_and_preserves_context_and_final_ids(self) -> None:
        event = MemoryContextRequest(
            session_id="s1", query="hello", speaker_id="u1", private=True
        )
        expected = MemoryContext(
            text="recall block",
            info={
                "mode": "normal",
                "picked": 2,
                "chars": 12,
                "final_ids": ("a1", "a2"),
            },
        )
        seen = []

        def build(request):
            seen.append(request)
            return expected

        adapter = SeekMemoryContextAdapter(build)
        context = adapter.build_context(event)
        self.assertIs(context, expected)
        self.assertIs(seen[0], event)
        self.assertEqual(context.info["final_ids"], ("a1", "a2"))

    def test_adapter_composes_with_agent_runtime(self) -> None:
        calls = []

        def build(request):
            calls.append((request.query, request.session_id))
            return MemoryContext(text="block", info={"final_ids": ("a1",)})

        runtime = AgentRuntime(
            InMemoryStateStore(),
            memory_context=SeekMemoryContextAdapter(build),
        )
        context = runtime.build_context(RuntimeInput("s1", "hello"))
        self.assertEqual(context.text, "block")
        self.assertEqual(context.info["final_ids"], ("a1",))
        self.assertEqual(calls, [("hello", "s1")])

    def test_adapter_imports_from_plugin_package_and_top_level(self) -> None:
        top_level = (
            "from adapters.seekmemory_context import SeekMemoryContextAdapter; "
            "from app.runtime import MemoryContext; "
            "assert SeekMemoryContextAdapter(lambda request: MemoryContext("
            "text='x', info={'final_ids': ('1',)})).build_context(None).info"
            "['final_ids'] == ('1',)"
        )
        package = (
            f"from {ROOT.name}.adapters.seekmemory_context import "
            "SeekMemoryContextAdapter; "
            f"from {ROOT.name}.app.runtime import MemoryContext; "
            "assert SeekMemoryContextAdapter(lambda request: MemoryContext("
            "text='x', info={'final_ids': ('1',)})).build_context(None).info"
            "['final_ids'] == ('1',)"
        )
        for cwd, code in ((ROOT, top_level), (ROOT.parent, package)):
            with self.subTest(cwd=cwd):
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_main_inject_memory_path_is_runnable_without_host(self) -> None:
        script = r"""
import asyncio
import importlib
import json
import logging
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

root = Path(sys.argv[1])
sys.path.insert(0, str(root.parent))

astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("fake-astrbot")


class Star:
    def __init__(self, *args, **kwargs):
        pass


api.star = SimpleNamespace(Star=Star, Context=object)
event_module = types.ModuleType("astrbot.api.event")


class AstrMessageEvent:
    pass


class Filter:
    class EventMessageType:
        ALL = "all"

    def __getattr__(self, name):
        def decorator(*args, **kwargs):
            return lambda function: function

        return decorator


event_module.AstrMessageEvent = AstrMessageEvent
event_module.filter = Filter()
core = types.ModuleType("astrbot.core")
utils = types.ModuleType("astrbot.core.utils")
utils_path = types.ModuleType("astrbot.core.utils.astrbot_path")
utils_path.get_astrbot_plugin_data_path = lambda: str(root / "plugin-data")
sys.modules.update(
    {
        "astrbot": astrbot,
        "astrbot.api": api,
        "astrbot.api.event": event_module,
        "astrbot.core": core,
        "astrbot.core.utils": utils,
        "astrbot.core.utils.astrbot_path": utils_path,
    }
)

main_module = importlib.import_module(f"{root.name}.main")
runtime_module = importlib.import_module(f"{root.name}.app.runtime")
tracing_module = importlib.import_module(f"{root.name}.app.runtime.tracing")
trace_store_module = importlib.import_module(f"{root.name}.store.run_trace")
adapter_module = importlib.import_module(
    f"{root.name}.adapters.seekmemory_context"
)
journal_module = importlib.import_module(f"{root.name}.webui.journal")


class Event:
    unified_msg_origin = "bot:FriendMessage:alice"
    message_str = "hello"

    def __init__(self):
        self.extras = {}

    def is_private_chat(self):
        return True

    def get_sender_id(self):
        return "u1"

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


class FakeCapacity:
    def __init__(self):
        self.context_chars = 0

    def set_context_chars(self, value):
        self.context_chars = value


class FakeMain(main_module.Main):
    def __init__(self, data_dir):
        self.ready = True
        self.capacity_service = FakeCapacity()
        self.cache = object()
        self.data_path = Path(data_dir) / "memory.db"
        self.journal = journal_module.Journal(Path(data_dir) / "journal.jsonl")
        self.run_traces = trace_store_module.TraceStore(
            Path(data_dir) / "run_traces.jsonl"
        )
        self.run_tracer = tracing_module.RunTracer(self.run_traces)
        self.calls = []
        self.runtime = runtime_module.AgentRuntime(
            runtime_module.InMemoryStateStore(),
            memory_context=adapter_module.SeekMemoryContextAdapter(
                self._runtime_memory_context
            ),
        )
        self.services = SimpleNamespace(
            runtime=self.runtime,
            capacity_service=self.capacity_service,
        )

    def _may_recall(self, event):
        return True

    def _c(self, key, default):
        return default

    def _recall_block(self, text, umo="", private=False, speaker=""):
        self.calls.append((text, umo, private, speaker))
        if len(self.calls) == 1:
            return "memory block", {
                "mode": "normal",
                "picked": 2,
                "chars": 12,
                "pinned": 1,
                "final_ids": ["a1", 2],
            }
        return "", {
            "mode": "strict",
            "picked": 0,
            "chars": 0,
            "final_ids": ("a1",),
        }


with tempfile.TemporaryDirectory() as temp:
    plugin = FakeMain(temp)
    event = Event()
    req = SimpleNamespace(system_prompt="base")
    asyncio.run(plugin.inject_memory(event, req))
    assert plugin.calls == [
        ("hello", "bot:FriendMessage:alice", True, "u1")
    ], plugin.calls
    assert event.get_extra("_seekmemory_recall_ids") == ("a1", "2")
    assert req.system_prompt.startswith("base") and "memory block" in req.system_prompt
    assert plugin.services.capacity_service.context_chars == len("memory block")
    trace = plugin.run_traces.snapshot()
    assert trace["events"][0]["event"] == "llm_request"
    assert trace["events"][0]["recall"]["artifact_ids"] == ["a1"]
    assert "memory block" not in json.dumps(trace)
    journal = plugin.journal.events[-1]
    assert (
        journal["kind"], journal["status"], journal["stage"]
    ) == ("recall", "info", "assemble")
    assert journal["context"] == {
        "mode": "normal",
        "picked": 2,
        "chars": 12,
    }, journal["context"]
    with open(plugin._calls_path(), encoding="utf-8") as stream:
        logged = json.loads(stream.readlines()[-1])
    assert (
        logged["kind"], logged["mode"], logged["picked"], logged["chars"]
    ) == ("FriendMessage", "normal", 2, 12), logged

    empty_event = Event()
    empty_req = SimpleNamespace(system_prompt="base")
    asyncio.run(plugin.inject_memory(empty_event, empty_req))
    assert empty_req.system_prompt == "base"
    assert empty_event.get_extra("_seekmemory_recall_ids") == ("a1",)
    assert plugin.services.capacity_service.context_chars == 0

    def fail_recall(text, umo="", private=False, speaker=""):
        raise RuntimeError("db path /secret")

    plugin._recall_block = fail_recall
    failed_event = Event()
    failed_req = SimpleNamespace(system_prompt="base")
    asyncio.run(plugin.inject_memory(failed_event, failed_req))
    assert failed_req.system_prompt == "base"
    assert failed_event.get_extra("_seekmemory_recall_ids") is None
    failed_journal = plugin.journal.events[-1]
    assert (failed_journal["kind"], failed_journal["status"]) == (
        "recall",
        "failed",
    )
    assert failed_journal["error"]["type"] == "RuntimeError"
    serialized = json.dumps(failed_journal)
    assert "hello" not in serialized
    assert "/secret" not in serialized

print("ok")
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
