"""Deterministic one-hour Runtime soak across deferred, proactive and audited sends."""

from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    ActionExecutor, ActionLedger, AgentRuntime, DefaultProactivePolicy,
    RepoStateStore, RunContext, RunRecorder, RuntimeInput, RuntimeWorker, Scheduler,
)
from app.runtime.contracts import ActionResult, ActionStatus  # noqa: E402
from store import open_store  # noqa: E402


class RuntimeSoakTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_hour_mixed_lanes_have_no_lost_work_or_duplicate_sends(self) -> None:
        db = open_store(":memory:")
        self.addCleanup(db.close)
        now = 1_000.0
        sessions = [f"lane-{index}" for index in range(8)]
        sends: list[tuple[str, str]] = []
        prompts: list[tuple[str, str]] = []
        failures: set[str] = set()
        audit = []

        async def complete(session: str, prompt: str, _system: str | None) -> str:
            prompts.append((session, prompt))
            if prompt == "input-0-lane-0" and prompt not in failures:
                failures.add(prompt)
                raise RuntimeError("temporary model failure")
            return f"reply-{len(prompts)}"

        async def send(request) -> ActionResult:
            sends.append((request.session_id, request.text))
            return ActionResult(True)

        store = RepoStateStore(db.runtime_state)
        runtime = AgentRuntime(
            store, clock=lambda: now, wait_seconds=20,
            recorder=RunRecorder(sources=db.sources, buffer=None, checkpoint=None, episodes=None),
            model_gateway=SimpleNamespace(complete=complete),
            action_executor=ActionExecutor(
                SimpleNamespace(execute=send),
                ActionLedger(SimpleNamespace(append=audit.append)), clock=lambda: now,
            ),
            source_reader=db.sources, run_control_enabled=True,
        )

        def run_context(lane: str, moment: float) -> RunContext:
            source = db.sources.latest_user_source(lane)
            return RunContext(
                lane, str(source["text"]), source_id=str(source["id"]), received_at=moment,
            )

        worker = RuntimeWorker(
            runtime=runtime, scheduler=Scheduler(store), enabled=lambda: True,
            session_ids=lambda _: sessions, run_context=run_context,
            interval_seconds=lambda: 30, max_attempts=lambda: 3,
            base_seconds=lambda: 2, clock=lambda: now, max_concurrency=3,
            proactive_policy=DefaultProactivePolicy(
                enabled=True, cooldown_seconds=120, ignored_backoff_seconds=0,
            ), proactive_max_fanout=2,
        )

        accepted = []
        admission_ms: list[float] = []
        max_due = 0
        for minute in range(60):
            now = 1_000.0 + minute * 60
            active = sessions if minute % 10 == 0 else [sessions[minute % len(sessions)]]
            for lane in active:
                started_ns = time.perf_counter_ns()
                accepted.append(runtime.accept_user(RuntimeInput(
                    lane, f"input-{minute}-{lane}", event_id=f"event-{minute}-{lane}",
                    speaker_id="user", event_time=now,
                ), now=now))
                admission_ms.append((time.perf_counter_ns() - started_ns) / 1_000_000)
                runtime.schedule_proactive(lane, 120, now=now)
            now += 30
            max_due = max(max_due, len(Scheduler(store).due(sessions, now)))
            await worker.tick(now=now)

        now += 180
        await worker.tick(now=now)
        sent_after_drain = len(sends)
        await worker.tick(now=now)
        self.assertEqual(len(sends), sent_after_drain)
        self.assertEqual(len(accepted), 102)
        self.assertTrue(all(receipt.source_id for receipt in accepted))
        self.assertGreater(len(sends), len(accepted))  # proactive sends joined the same audited path
        self.assertGreaterEqual(max_due, len(sessions))
        self.assertEqual(failures, {"input-0-lane-0"})
        self.assertEqual(len(prompts), len(sends) + 1)  # one failed call, then a retry
        self.assertEqual(len(audit), 2 * len(sends))
        self.assertEqual(sum(row.status is ActionStatus.ATTEMPTED for row in audit), len(sends))
        self.assertEqual(sum(row.status is ActionStatus.SUCCEEDED for row in audit), len(sends))
        self.assertEqual(len({row.action_id for row in audit}), len(sends))
        for lane in sessions:
            state = store.get(lane)
            self.assertEqual(state.unread_count, 0)
            self.assertEqual(state.unread_sources, {})
            self.assertEqual(state.proactive_due_at, 0)
            self.assertEqual(state.next_retry_at, 0)
        replies = [source for source in db.sources.recent_sources(since="", limit=500)
                   if source.role == "assistant"]
        self.assertEqual(len(replies), len(sends))
        if os.environ.get("SEEKMEMORY_RUNTIME_SOAK_REPORT") == "1":
            sorted_ms = sorted(admission_ms)
            print(json.dumps({
                "virtual_minutes": 60, "lanes": len(sessions),
                "admission_p50_ms": sorted_ms[len(sorted_ms) // 2],
                "admission_p95_ms": sorted_ms[int(len(sorted_ms) * .95) - 1],
                "max_due_depth": max_due, "dispatched": len(sends),
                "model_failures": len(failures),
                "proactive_sends": len(sends) - len(accepted),
                "duplicate_action_ids": len(sends) - len({row.action_id for row in audit}),
            }, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
