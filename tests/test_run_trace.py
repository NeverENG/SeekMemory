"""Run correlation, bounded persistence and content exclusion regressions."""
from __future__ import annotations

import json
import ast
import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.tracing import RunTracer
from app.runtime import AgentRuntime, MemoryContext
from adapters.astrbot.runtime import AstrBotRuntimeAdapter
from adapters.astrbot.context import SeekMemoryContextAdapter
from store.run_trace import TraceStore


class Event:
    def __init__(self):
        self.extras = {}

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value


class RunTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "trace.jsonl"
        self.now = 1_800_000_000.0
        self.store = TraceStore(self.path, clock=lambda: self.now)
        self.tracer = RunTracer(self.store, clock=lambda: self.now)

    def test_interleaved_runs_repeated_requests_and_delivery(self):
        a, b = Event(), Event()
        self.tracer.begin(a)
        self.tracer.begin(b)
        self.tracer.request(a, {"mode": "strict", "final_ids": ["n_1"],
                                "picked_ids": ["n_1"], "chars": 10})
        self.tracer.request(b, {"mode": "none", "chars": 0})
        self.tracer.response(a, "ok")
        self.tracer.request(a, {"mode": "strict", "final_ids": ["n_2"], "chars": 5})
        self.tracer.done(a, "ok")
        self.tracer.delivered(a)
        self.tracer.delivered(a)
        rows = self.store.snapshot()["events"]
        runs = {row["run_id"] for row in rows}
        self.assertEqual(len(runs), 2)
        requests = [row for row in rows if row["event"] == "llm_request"]
        self.assertEqual([row["request_index"] for row in requests], [1, 1, 2])
        self.assertEqual(sum(row["event"] == "message_sent" for row in rows), 1)
        self.assertEqual(self.store.snapshot("recalled_and_injected")["runs"][0]["delivered"], True)
        self.assertEqual(len(self.store.snapshot("not_recalled")["runs"]), 1)

    def test_content_is_excluded_at_write_and_reload(self):
        event = Event()
        secret = "RAW_QUERY_RESPONSE_TOOL_ARGUMENT"
        self.tracer.begin(event)
        self.tracer.request(event, {"mode": secret, "text": secret, "query": secret,
            "fallback": secret, "final_ids": ["n_1"],
            "disclosure": {"n_2": "silence"}, "response": secret})
        tool = SimpleNamespace(name="weather")
        self.tracer.tool_begin(event, tool)
        self.now += 0.2
        self.tracer.tool_end(event, tool)
        self.assertNotIn(secret, self.path.read_text())
        with self.path.open("a") as stream:
            stream.write('{broken\n')
            row = self.store.snapshot()["events"][0] | {"query": secret}
            stream.write(json.dumps(row) + "\n")
        restored = TraceStore(self.path, clock=lambda: self.now)
        self.assertNotIn(secret, json.dumps(restored.snapshot()))
        result = [r for r in restored.snapshot()["events"] if r["event"] == "tool_result"][0]
        self.assertAlmostEqual(result["duration_ms"], 200, places=2)
        self.assertEqual(result["status"], "unknown")

    def test_count_age_restart_and_failed_write(self):
        store = TraceStore(self.path, max_rows=2, retention_days=7, clock=lambda: self.now)
        tracer = RunTracer(store, clock=lambda: self.now)
        event = Event()
        tracer.begin(event)
        tracer.request(event, {})
        tracer.done(event, "error")
        self.assertEqual(len(self.path.read_text().splitlines()), 2)
        self.assertTrue(store.snapshot()["runs"][0]["partial"])
        self.now += 8 * 86400
        self.assertEqual(store.snapshot()["events"], [])
        self.assertEqual(TraceStore(self.path, clock=lambda: self.now).snapshot()["runs"], [])
        with patch.object(Path, "open", side_effect=OSError("private error")):
            tracer.begin(Event())
        self.assertEqual(store.snapshot()["events"], [])
        self.assertTrue(store.persistence_error)
        tracer.begin(Event())
        self.assertFalse(store.persistence_error)
        self.assertEqual(len(store.snapshot()["events"]), 1)

    def test_failed_compaction_preserves_existing_file_and_recovers(self):
        store = TraceStore(self.path, max_rows=1, clock=lambda: self.now)
        tracer = RunTracer(store, clock=lambda: self.now)
        event = Event()
        tracer.begin(event)
        before = self.path.read_bytes()
        with patch("store.run_trace.os.replace", side_effect=OSError("private error")):
            tracer.request(event, {})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(store.snapshot()["events"][0]["event"], "agent_begin")
        self.assertTrue(store.persistence_error)
        tracer.done(event, "ok")
        self.assertFalse(store.persistence_error)
        self.assertEqual(store.snapshot()["events"][0]["event"], "agent_done")

    def test_invalid_utf8_lines_are_ignored_on_reload(self) -> None:
        event = Event()
        self.tracer.begin(event)
        with self.path.open("ab") as stream:
            stream.write(b"\xff\n")
        restored = TraceStore(self.path, clock=lambda: self.now)
        self.assertEqual(restored.snapshot()["runs"][0]["event_count"], 1)

    def test_read_only_snapshots_age_without_rewriting_or_accepting_events(self) -> None:
        self.tracer.begin(Event())
        original = self.path.read_bytes()
        reader = TraceStore(self.path, read_only=True, clock=lambda: self.now)
        self.assertEqual(len(reader.snapshot()["events"]), 1)
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(PermissionError):
            reader.append(reader.snapshot()["events"][0])
        self.now += 8 * 86400
        self.assertEqual(reader.snapshot()["events"], [])
        self.assertEqual(self.path.read_bytes(), original)

    def test_read_only_missing_trace_creates_no_file_or_directory(self) -> None:
        missing = Path(self.temp.name) / "missing" / "trace.jsonl"
        reader = TraceStore(missing, read_only=True, clock=lambda: self.now)
        self.assertEqual(reader.snapshot()["events"], [])
        self.assertFalse(missing.parent.exists())

    def test_stale_unfinished_run_is_interrupted_after_restart(self) -> None:
        event = Event()
        self.tracer.begin(event)
        restored = TraceStore(self.path, clock=lambda: self.now + 60)
        run = restored.snapshot()["runs"][0]
        self.assertEqual(run["status"], "interrupted")

    def test_missing_middle_event_marks_timeline_partial(self):
        event = Event()
        self.tracer.begin(event)
        with patch.object(Path, "open", side_effect=OSError("unavailable")):
            self.tracer.request(event, {})
        self.tracer.done(event, "ok")
        self.assertEqual([r["sequence"] for r in self.store.snapshot()["events"]], [1, 3])
        self.assertTrue(self.store.snapshot()["runs"][0]["partial"])

    def test_withheld_and_fallback_are_independent_filters(self):
        event = Event()
        self.tracer.request(event, {"mode": "loose", "fallback": "recent_topic",
            "picked_ids": ["n_1"], "final_ids": ["n_1"],
            "disclosure": {"n_1": "full", "n_2": "silence"}})
        self.tracer.done(event, "error")
        for state in ("fallback_used", "recalled_but_withheld", "recalled_and_injected"):
            runs = self.store.snapshot(state)["runs"]
            self.assertEqual(len(runs), 1)
            self.assertFalse(runs[0]["delivered"])
        self.assertEqual(self.store.snapshot()["runs"][0]["status"], "error")

    def test_host_ordering_and_overlapping_tools_do_not_invent_evidence(self):
        event = Event()
        self.tracer.delivered(event)  # Unrelated non-agent messages are not new runs.
        self.assertEqual(self.store.snapshot()["events"], [])
        self.tracer.request(event, None)
        self.tracer.begin(event)  # The request hook can precede agent_begin.
        tool = SimpleNamespace(name="weather")
        self.tracer.tool_begin(event, tool)
        self.now += 1
        self.tracer.tool_begin(event, tool)
        self.tracer.tool_end(event, tool)
        self.tracer.tool_end(event, tool)
        snapshot = self.store.snapshot()
        self.assertFalse(snapshot["runs"][0]["partial"])
        self.assertEqual(snapshot["runs"][0]["flags"], [])
        results = [r for r in snapshot["events"] if r["event"] == "tool_result"]
        self.assertEqual([r["duration_ms"] for r in results], [None, None])
        self.tracer.done(event, "ok")
        self.tracer.request(event, {})
        self.tracer.begin(event)
        self.assertEqual(len(self.store.snapshot()["runs"]), 2)

    def test_writer_failure_is_fail_open_and_large_valid_events_reload(self):
        broken = SimpleNamespace(append=lambda row: (_ for _ in ()).throw(OSError("secret")))
        tracer = RunTracer(broken)
        event = Event()
        tracer.begin(event)
        tracer.request(event, {})
        tracer.response(event, "ok")
        tracer.done(event, "ok")
        tracer.delivered(event)
        ids = [str(i).zfill(96) for i in range(256)]
        info = {key: ids for key in ("picked_ids", "pinned_ids", "final_ids", "dropped_ids")}
        info["disclosure"] = {key: "silence" for key in ids}
        self.tracer.request(Event(), info)
        self.assertGreater(self.path.stat().st_size, 65536)
        self.assertEqual(TraceStore(self.path, clock=lambda: self.now).snapshot()["events"],
                         self.store.snapshot()["events"])

    def test_request_hook_preserves_prompt_and_reports_skipped_and_failed_recall(self):
        # Execute the production hook/plugin bodies without importing AstrBot.
        # This protects the mapping; it is NOT real-host integration verification.
        root = Path(__file__).resolve().parents[1]
        hooks_source = ast.parse((root / "adapters" / "astrbot" / "hooks.py").read_text())
        plugin_source = ast.parse((root / "adapters" / "astrbot" / "plugin.py").read_text())
        hooks_cls = next(
            n for n in hooks_source.body
            if isinstance(n, ast.ClassDef) and n.name == "AstrBotHooks"
        )
        plugin_cls = next(
            n for n in plugin_source.body
            if isinstance(n, ast.ClassDef) and n.name == "AstrBotPlugin"
        )
        hook_names = {"inject_memory", "capture_reply", "record_delivery",
                      "observe_agent_begin"}
        plugin_names = {"_runtime_memory_context"}
        methods = [n for n in hooks_cls.body
                   if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                   and n.name in hook_names]
        methods += [n for n in plugin_cls.body
                    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and n.name in plugin_names]
        main = ast.ClassDef(name="Main", bases=[], keywords=[], body=methods,
                            decorator_list=[])
        module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), main], type_ignores=[])
        namespace = {
            "AstrBotRuntimeAdapter": AstrBotRuntimeAdapter,
            "MemoryContext": MemoryContext,
            "log_call": Mock(),
            "logger": Mock(),
            "datetime": __import__("datetime"),
        }
        exec(compile(ast.fix_missing_locations(module), "main.py", "exec"), namespace)
        plugin = namespace["Main"]()
        plugin._bindings = plugin
        plugin.ready, plugin.cache, plugin.store = True, {}, None
        plugin.clock = lambda: self.now
        plugin.run_tracer, plugin.journal, plugin.trace = self.tracer, Mock(), Mock()
        plugin._may_recall = plugin._may_observe = lambda event: True
        plugin._calls_path = lambda: "unused"
        plugin._c = lambda key, default: default
        plugin._recall_block = lambda *args: ("SAFE MEMORY", {"final_ids": ["n_1"], "mode": "strict", "picked": 1, "chars": 11})
        plugin.services = SimpleNamespace(
            runtime=AgentRuntime(
                store=Mock(),
                memory_context=SeekMemoryContextAdapter(
                    plugin._runtime_memory_context
                ),
            ),
            capacity_service=SimpleNamespace(set_context_chars=lambda _value: None),
        )
        event = Event()
        event.message_str = "PRIVATE QUESTION"
        event.get_sender_id = lambda: "PRIVATE USER"
        req = SimpleNamespace(system_prompt="original")
        asyncio.run(plugin.inject_memory(event, req))
        asyncio.run(plugin.observe_agent_begin(event, None))
        asyncio.run(plugin.capture_reply(event, SimpleNamespace(role="assistant")))
        asyncio.run(plugin.record_delivery(event))
        self.assertTrue(req.system_prompt.startswith("original\n\n【你的记忆】"))
        self.assertIn("SAFE MEMORY", req.system_prompt)
        run = self.store.snapshot()["runs"][0]
        self.assertTrue(run["delivered"])
        self.assertFalse(run["partial"])
        self.assertIn("recalled_and_injected", run["flags"])
        self.assertNotIn("PRIVATE", self.path.read_text())
        self.assertNotIn("SAFE MEMORY", self.path.read_text())
        plugin._recall_block = Mock(side_effect=RuntimeError("private failure"))
        asyncio.run(plugin.inject_memory(event, req))
        self.assertEqual(self.store.snapshot()["events"][-1]["status"], "error")
        plugin.ready = False
        asyncio.run(plugin.inject_memory(event, req))
        self.assertIsNone(self.store.snapshot()["events"][-1]["recall"])
        count = len(self.store.snapshot()["events"])
        plugin._may_recall = lambda event: False
        asyncio.run(plugin.inject_memory(event, req))
        self.assertEqual(len(self.store.snapshot()["events"]), count)


if __name__ == "__main__":
    unittest.main()
