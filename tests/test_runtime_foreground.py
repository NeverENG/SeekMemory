"""Process-local foreground admission through the AgentRuntime owner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import AgentRuntime, InMemoryStateStore  # noqa: E402
from app.runtime.foreground import TaskPriority, TaskStatus  # noqa: E402


class ForegroundSchedulingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = AgentRuntime(InMemoryStateStore())
        self.scheduler = self.runtime.foreground

    def test_priority_and_fifo_within_a_priority_class(self) -> None:
        first = self.scheduler.submit("conversation", "host-a/lane-a", TaskPriority.INTERACTIVE)
        second = self.scheduler.submit("conversation", "host-a/lane-b", TaskPriority.INTERACTIVE)
        background = self.scheduler.submit("dream", "host-b/lane-a", TaskPriority.BACKGROUND)
        self.assertEqual(self.scheduler.claim_next().task_id, first.task_id)
        self.assertIsNone(self.scheduler.claim_next())
        self.assertTrue(self.scheduler.finish(first.task_id))
        self.assertEqual(self.scheduler.claim_next().task_id, second.task_id)
        self.assertTrue(self.scheduler.finish(second.task_id))
        self.assertEqual(self.scheduler.claim_next().task_id, background.task_id)

    def test_higher_priority_waits_for_a_real_checkpoint_and_resume_is_explicit(self) -> None:
        background = self.scheduler.submit("browse", "host-a/lane-a", TaskPriority.BACKGROUND)
        self.assertEqual(self.scheduler.claim_next().task_id, background.task_id)
        interactive = self.scheduler.submit("conversation", "host-a/lane-b", TaskPriority.INTERACTIVE)
        self.assertEqual(self.scheduler.current().status, TaskStatus.YIELD_REQUESTED)
        self.assertIsNone(self.scheduler.claim_next())
        self.assertTrue(self.scheduler.yield_at_checkpoint(background.task_id))
        self.assertEqual(self.scheduler.view(background.task_id).status, TaskStatus.SUSPENDED)
        self.assertEqual(self.scheduler.claim_next().task_id, interactive.task_id)
        self.assertFalse(self.scheduler.yield_at_checkpoint(background.task_id))
        self.assertFalse(self.scheduler.finish(background.task_id))
        self.assertEqual(self.scheduler.current().task_id, interactive.task_id)
        self.assertTrue(self.scheduler.resume(background.task_id))
        self.assertTrue(self.scheduler.finish(interactive.task_id))
        self.assertEqual(self.scheduler.claim_next().task_id, background.task_id)

    def test_late_completion_cannot_release_another_task(self) -> None:
        old = self.scheduler.submit("conversation", "host-a/lane-a", TaskPriority.INTERACTIVE)
        self.scheduler.claim_next()
        self.assertTrue(self.scheduler.finish(old.task_id))
        current = self.scheduler.submit("conversation", "host-a/lane-a", TaskPriority.INTERACTIVE)
        self.scheduler.claim_next()
        self.assertFalse(self.scheduler.finish(old.task_id))
        self.assertFalse(self.scheduler.yield_at_checkpoint(old.task_id))
        self.assertEqual(self.scheduler.current().task_id, current.task_id)

    def test_ready_background_work_is_not_starved_by_interactive_claims(self) -> None:
        background = self.scheduler.submit("dream", "b", TaskPriority.BACKGROUND)
        for index in range(4):
            self.scheduler.submit("conversation", f"c{index}", TaskPriority.INTERACTIVE)
        for _ in range(3):
            claimed = self.scheduler.claim_next()
            self.assertEqual(claimed.priority, TaskPriority.INTERACTIVE)
            self.assertTrue(self.scheduler.finish(claimed.task_id))
        self.assertEqual(self.scheduler.claim_next().task_id, background.task_id)

    def test_withdrawn_high_priority_work_does_not_force_an_empty_yield(self) -> None:
        background = self.scheduler.submit("browse", "b", TaskPriority.BACKGROUND)
        self.scheduler.claim_next()
        interactive = self.scheduler.submit("conversation", "c", TaskPriority.INTERACTIVE)
        self.assertEqual(self.scheduler.current().status, TaskStatus.YIELD_REQUESTED)
        self.assertTrue(self.scheduler.abandon(interactive.task_id))
        self.assertEqual(self.scheduler.current().status, TaskStatus.RUNNING)
        self.assertFalse(self.scheduler.yield_at_checkpoint(background.task_id))
        self.assertTrue(self.scheduler.finish(background.task_id))
        self.assertIsNone(self.scheduler.claim_next())

    def test_only_nonrunning_tasks_can_be_abandoned(self) -> None:
        active = self.scheduler.submit("conversation", "a", TaskPriority.INTERACTIVE)
        self.scheduler.claim_next()
        pending = self.scheduler.submit("conversation", "b", TaskPriority.INTERACTIVE)
        self.assertFalse(self.scheduler.abandon(active.task_id))
        self.assertTrue(self.scheduler.abandon(pending.task_id))
        self.assertIsNone(self.scheduler.view(pending.task_id))
        self.assertEqual(self.scheduler.current().task_id, active.task_id)

    def test_owners_do_not_share_foreground_slots(self) -> None:
        first = self.scheduler.submit("conversation", "lane", TaskPriority.INTERACTIVE)
        self.scheduler.claim_next()
        other = AgentRuntime(InMemoryStateStore()).foreground
        second = other.submit("conversation", "lane", TaskPriority.INTERACTIVE)
        self.assertEqual(other.claim_next().task_id, second.task_id)
        self.assertFalse(other.finish(first.task_id))
        self.assertEqual(self.scheduler.current().task_id, first.task_id)

    def test_injected_pure_policy_controls_selection_and_yield_request(self) -> None:
        class LatestFirstPolicy:
            def pick(self, ready, consecutive_interactive):
                return ready[-1].task_id if ready else None

            def should_yield(self, active, incoming):
                return False

        scheduler = AgentRuntime(InMemoryStateStore(), scheduling_policy=LatestFirstPolicy()).foreground
        first = scheduler.submit("browse", "a", TaskPriority.BACKGROUND)
        second = scheduler.submit("browse", "b", TaskPriority.BACKGROUND)
        self.assertEqual(scheduler.claim_next().task_id, second.task_id)
        scheduler.submit("conversation", "c", TaskPriority.INTERACTIVE)
        self.assertEqual(scheduler.current().status, TaskStatus.RUNNING)
        self.assertFalse(scheduler.yield_at_checkpoint(second.task_id))
        self.assertTrue(scheduler.finish(second.task_id))
        self.assertNotEqual(scheduler.claim_next().task_id, second.task_id)
        self.assertIsNotNone(scheduler.view(first.task_id))


class ForegroundAsyncAdmissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_waiter_claims_only_the_task_selected_by_policy(self) -> None:
        class AlternatingPolicy:
            def __init__(self):
                self.calls = 0

            def pick(self, ready, consecutive_interactive):
                self.calls += 1
                return ready[self.calls % len(ready)].task_id if ready else None

            def should_yield(self, active, incoming):
                return False

        policy = AlternatingPolicy()
        scheduler = AgentRuntime(InMemoryStateStore(), scheduling_policy=policy).foreground
        first = scheduler.submit("worker", "a", TaskPriority.BACKGROUND)
        second = scheduler.submit("worker", "b", TaskPriority.BACKGROUND)
        claimed = await scheduler.claim_when_ready(second.task_id)
        self.assertEqual(claimed.task_id, second.task_id)
        self.assertEqual(policy.calls, 1)
        self.assertEqual(scheduler.view(first.task_id).status, TaskStatus.READY)

    async def test_invalid_policy_fails_instead_of_leaving_waiter_pending(self) -> None:
        class EmptyPolicy:
            def pick(self, ready, consecutive_interactive):
                return None

            def should_yield(self, active, incoming):
                return False

        scheduler = AgentRuntime(InMemoryStateStore(), scheduling_policy=EmptyPolicy()).foreground
        waiting = scheduler.submit("worker", "a", TaskPriority.BACKGROUND)
        with self.assertRaisesRegex(ValueError, "select a ready task"):
            await scheduler.claim_when_ready(waiting.task_id)
        self.assertTrue(scheduler.abandon(waiting.task_id))


if __name__ == "__main__":
    unittest.main()
