"""梦境周期与上下文预算的回归测试。"""

from __future__ import annotations

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.budget import (  # noqa: E402
    ContextBudget,
    budget_from_config,
    clamp_chars,
    estimate_tokens,
)
from app.dream import DreamCycle  # noqa: E402
from app.flush_policy import decide_flush  # noqa: E402


class FakeStore:
    """最小台账桩：只实现 dream 相关读写。"""

    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def get(self, date):
        return self.runs.get(date)

    def begin(self, date, now=""):
        run = self.runs.get(date)
        if run and run.get("status") == "done":
            return False
        self.runs[date] = {"date": date, "status": "running", "started_at": now}
        return True

    def finish(self, date, *, status="done", batches=0, written=0,
                     errors=None, summary=None, now=""):
        self.runs[date] = {"date": date, "status": status, "batches": batches,
                           "written": written, "errors": errors or [],
                           "summary": summary or {}, "finished_at": now}

    def recent(self, limit=7):
        return list(self.runs.values())[:limit]


def conf(**kw):
    """配置桩：给定键优先，其余回默认。"""
    def _c(key, default):
        return kw.get(key, default)
    return _c


AT = datetime.datetime(2026, 10, 24, 3, 31)


class DreamDueTest(unittest.TestCase):
    def test_before_dream_time_not_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_time="03:30"))
        self.assertFalse(dream.due(datetime.datetime(2026, 10, 24, 3, 0)))

    def test_after_dream_time_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_time="03:30"))
        self.assertTrue(dream.due(AT))

    def test_disabled_never_due(self):
        dream = DreamCycle(FakeStore(), conf(dream_enabled=False))
        self.assertFalse(dream.due(AT))


class DreamRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_finish_failure_preserves_counts_and_reports_failure(self):
        class BrokenJournal(FakeStore):
            def finish(self, *args, **kwargs):
                raise OSError("private prompt secret")
        left, logs = [1], []
        async def flush(*args, **kwargs):
            left[0] = 0
            return 3, 1
        dream = DreamCycle(BrokenJournal(), conf(), log=logs.append)
        result = await dream.run(flush, pending=lambda: left[0], now=AT)
        self.assertEqual((result.status, result.reason), ("failed", "journal_finish_failed"))
        self.assertEqual((result.written, result.batches), (3, 1))
        self.assertEqual(left[0], 0)
        self.assertNotIn("private prompt secret", str(result) + str(logs))
        self.assertTrue(dream.due(AT))

    async def test_failed_diagnostics_do_not_change_completed_cycle(self):
        def log(message):
            raise OSError("diagnostics unavailable")
        async def flush(*args, **kwargs):
            return 0, 0
        store = FakeStore()
        result = await DreamCycle(store, conf(), log=log).run(flush, pending=lambda: 0, now=AT)
        self.assertEqual(result.status, "done")
        self.assertEqual(store.get(AT.date().isoformat())["status"], "done")

    async def test_extraction_error_keeps_only_stage_and_class(self):
        async def flush(*args, **kwargs):
            raise RuntimeError("private prompt secret")
        result = await DreamCycle(FakeStore(), conf()).run(flush, pending=lambda: 1, now=AT)
        self.assertEqual(result.errors, ("flush: RuntimeError",))

    async def test_runs_once_and_is_idempotent(self):
        store, calls, left = FakeStore(), [], {"pending": 1}

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            calls.append(1)
            left["pending"] = 0
            return 2, 1

        dream = DreamCycle(store, conf())
        first = await dream.run(flush, pending=lambda: left["pending"], now=AT)
        second = await dream.run(flush, pending=lambda: left["pending"], now=AT)
        self.assertEqual(first.status, "done")
        self.assertEqual(first.written, 2)
        self.assertEqual(second.status, "skipped")
        self.assertEqual(second.reason, "not_due")
        self.assertEqual(len(calls), 1)

    async def test_failure_keeps_pending_for_resume(self):
        store = FakeStore()

        async def boom(_reason, *, max_calls=0, max_tokens=0, triage=False):
            raise RuntimeError("model down")

        dream = DreamCycle(store, conf())
        result = await dream.run(boom, pending=lambda: 3, now=AT)
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.errors)
        # 失败后当天仍可续跑
        self.assertTrue(dream.due(AT))

        async def ok(_reason, *, max_calls=0, max_tokens=0, triage=False):
            return 1, 1

        again = await dream.run(ok, pending=lambda: 0, now=AT)
        self.assertEqual(again.status, "done")

    async def test_max_batches_bound(self):
        store, calls = FakeStore(), []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            calls.append(1)
            return 0, 1

        dream = DreamCycle(store, conf(dream_max_batches=2))
        await dream.run(flush, pending=lambda: 99, now=AT)
        self.assertEqual(len(calls), 2)

    async def test_dream_passes_triage_true_to_flush(self):
        store, seen = FakeStore(), []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            seen.append(triage)
            return 0, 0

        dream = DreamCycle(store, conf())
        await dream.run(flush, pending=lambda: 1, now=AT)
        self.assertEqual(seen, [True])

    async def test_maintain_runs_after_flush(self):
        store, seen = FakeStore(), []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            return 1, 1

        async def maintain():
            seen.append("maintain")
            return {"persona": True}

        dream = DreamCycle(store, conf())
        result = await dream.run(flush, pending=lambda: 0, maintain=maintain, now=AT)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.summary.get("persona"), True)


class FlushPolicyDreamTest(unittest.TestCase):
    def test_dream_only_blocks_everything(self):
        decision = decide_flush(
            pending=100, idle_seconds=999, worth_now=True, flushes_today=0,
            idle_flush_seconds=0, min_pending=1, max_flushes_per_day=9,
            backlog_flush_at=1, topic_age_seconds=1e9, dream_only=True,
        )
        self.assertFalse(decision.should)
        self.assertEqual(decision.reason, "dream_only")


class BudgetTest(unittest.TestCase):
    def test_estimate_scales_with_chars(self):
        self.assertLess(estimate_tokens(800), estimate_tokens(1600))

    def test_budget_from_config(self):
        budget = budget_from_config(conf(budget_chars=900, group_context_messages=20))
        self.assertEqual(budget.injection_chars, 900)
        self.assertEqual(budget.group_context_messages, 20)
        self.assertGreater(budget.estimate_tokens, 0)

    def test_clamp_cuts_at_punctuation(self):
        text, size = clamp_chars("第一句话。第二句话。第三句话。", 12)
        self.assertTrue(text.endswith("。"))
        self.assertLessEqual(len(text), 12)
        self.assertEqual(size, len("第一句话。第二句话。第三句话。"))

    def test_default_budget(self):
        self.assertGreater(ContextBudget().estimate_tokens, 1000)

    def test_source_recall_budget_parses_config(self):
        budget = budget_from_config(
            conf(
                source_recall_enabled="false",
                source_recall_hours=3,
                source_recall_max_candidates=5,
            )
        )
        self.assertFalse(budget.source_recall_enabled)
        self.assertEqual(budget.source_recall_hours, 3)
        self.assertEqual(budget.source_recall_max_candidates, 5)


class DreamBudgetTest(unittest.IsolatedAsyncioTestCase):
    async def test_token_budget_stops_before_next_flush_and_still_maintains(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 0, "cached": 0, "out": 0}
        calls = []
        maintained = []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            calls.append(1)
            usage["calls"] += 1
            usage["in"] += 400
            usage["out"] += 200
            return 1, 1

        async def maintain():
            maintained.append(1)
            return {"persona": True}

        dream = DreamCycle(
            store,
            conf(dream_token_budget=1000, dream_max_batches=5),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            maintain=maintain,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(maintained, [1])
        self.assertEqual(result.summary["budget"]["used"], 1200)
        self.assertEqual(result.summary["budget"]["stopped"], "token_budget")
        self.assertEqual(result.summary["usage"]["calls"], 2)
        self.assertEqual(result.summary["persona"], True)

    async def test_call_budget_stops_before_next_flush_and_still_maintains(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 0, "cached": 0, "out": 0}
        calls = []
        maintained = []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            calls.append(max_calls)
            usage["calls"] += 1
            usage["in"] += 10
            usage["out"] += 5
            return 1, 1

        async def maintain():
            maintained.append(1)
            return {"persona": True}

        dream = DreamCycle(
            store,
            conf(dream_max_calls=2, dream_token_budget=0, dream_max_batches=5),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            maintain=maintain,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls, [2, 1])
        self.assertEqual(maintained, [1])
        self.assertEqual(result.summary["budget"]["calls"], 2)
        self.assertEqual(result.summary["budget"]["calls_used"], 2)
        self.assertEqual(result.summary["budget"]["stopped"], "call_budget")
        self.assertEqual(result.summary["usage"]["calls"], 2)
        self.assertEqual(result.summary["persona"], True)

    async def test_token_budget_is_passed_to_flush_and_stops_after_one_call(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 0, "cached": 0, "out": 0}
        seen = []
        maintained = []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            seen.append((max_calls, max_tokens))
            usage["calls"] += 1
            usage["in"] += 100
            usage["out"] += 50
            return 1, 1

        async def maintain():
            maintained.append(1)
            return {"persona": True}

        dream = DreamCycle(
            store,
            conf(dream_max_calls=10, dream_token_budget=100, dream_max_batches=5),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            maintain=maintain,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0], (10, 100))
        self.assertEqual(maintained, [1])
        self.assertEqual(result.summary["budget"]["stopped"], "token_budget")
        self.assertEqual(result.summary["budget"]["used"], 150)

    async def test_zero_budget_records_usage_without_stopping(self):
        store = FakeStore()
        usage = {"calls": 0, "in": 10, "cached": 0, "out": 5}
        calls = []

        async def flush(_reason, *, max_calls=0, max_tokens=0, triage=False):
            calls.append(1)
            usage["calls"] += 1
            usage["in"] += 10
            usage["out"] += 5
            return 1, 1

        dream = DreamCycle(
            store,
            conf(dream_token_budget=0, dream_max_batches=2),
        )
        result = await dream.run(
            flush,
            pending=lambda: 10,
            usage=lambda: dict(usage),
            now=AT,
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.summary["budget"]["stopped"], "")
        self.assertEqual(result.summary["usage"]["in"], 20)
        self.assertEqual(result.summary["usage"]["out"], 10)


if __name__ == "__main__":
    unittest.main()
