"""Lane-local run validity and cooperative checkpoints, without host or store fixtures."""

from __future__ import annotations

import asyncio
import gc
import sys
import unittest
import weakref
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.contracts import ActiveRunView, RunKind, RunTransition, RunTrigger, RuntimeInput  # noqa: E402
from app.runtime.runs import RunClosedError, RunControl, RunSupersededError  # noqa: E402


class RunControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.control = RunControl()
        self.trigger = RunTrigger(RunKind.DEFERRED, None, now=10.0)

    def test_begin_exposes_metadata_and_policy_view(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        self.assertIs(self.control.current("lane-1"), handle)
        self.assertEqual(handle.lane_id, "lane-1")
        self.assertTrue(handle.run_id)
        self.assertEqual(handle.view(), ActiveRunView(handle.run_id, "lane-1", 1, RunKind.DEFERRED, 10.0))
        self.assertFalse(handle.is_superseded())
        self.assertTrue(handle.is_valid())
        handle.raise_if_invalid()

    def test_explicit_supersession_replaces_only_the_same_lane(self) -> None:
        old = self.control.begin("lane-1", self.trigger)
        other = self.control.begin("lane-2", self.trigger)
        self.assertTrue(self.control.supersede("lane-1", old.run_id))
        current = self.control.begin("lane-1", self.trigger)
        self.assertTrue(old.is_superseded())
        self.assertEqual(old.supersede_reason, "superseded")
        self.assertNotEqual(current.run_id, old.run_id)
        self.assertGreater(current.epoch, other.epoch)
        self.assertGreater(other.epoch, old.epoch)
        self.assertIs(self.control.current("lane-1"), current)
        self.assertFalse(current.is_superseded())
        self.assertIs(self.control.current("lane-2"), other)
        self.assertFalse(other.is_superseded())

    def test_begin_without_supersession_keeps_valid_active_work(self) -> None:
        old = self.control.begin("lane-1", self.trigger)
        transition = RunTransition(start_new=True, supersede_active=False)
        if transition.start_new:
            self.assertIsNone(self.control.begin("lane-1", self.trigger))
        self.assertIs(self.control.current("lane-1"), old)
        self.assertTrue(old.is_valid())
        old.raise_if_invalid()
        self.control.supersede("lane-1", old.run_id)
        current = self.control.begin("lane-1", self.trigger)
        self.assertEqual(current.epoch, old.epoch + 1)

    def test_supersede_matches_identity_and_preserves_the_first_reason(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        self.assertFalse(self.control.supersede("lane-2", handle.run_id))
        self.assertFalse(self.control.supersede("lane-1", "old-run"))
        self.assertFalse(handle.is_superseded())
        self.assertTrue(self.control.supersede("lane-1", handle.run_id, "new_input"))
        self.assertFalse(self.control.supersede("lane-1", handle.run_id, "another_input"))
        self.assertEqual(handle.supersede_reason, "new_input")
        self.assertIs(self.control.current("lane-1"), handle)

    def test_stale_finish_and_supersede_keep_the_replacement(self) -> None:
        old = self.control.begin("lane-1", self.trigger)
        self.control.supersede("lane-1", old.run_id)
        current = self.control.begin("lane-1", self.trigger)
        RunControl().finish(old)
        self.assertFalse(old.closed)
        self.control.finish(old)
        self.control.finish(replace(current))
        self.assertTrue(old.closed)
        self.assertFalse(current.closed)
        self.assertFalse(self.control.supersede("lane-1", old.run_id))
        self.assertIs(self.control.current("lane-1"), current)
        self.assertFalse(current.is_superseded())

    def test_finish_closes_old_handle_without_supersession_after_lane_reopens(self) -> None:
        old = self.control.begin("lane-1", self.trigger)
        self.control.finish(old)
        self.control.finish(old)
        self.assertIsNone(self.control.current("lane-1"))
        other = self.control.begin("lane-2", self.trigger)
        self.control.finish(other)
        current = self.control.begin("lane-1", self.trigger)
        self.assertGreater(other.epoch, old.epoch)
        self.assertGreater(current.epoch, other.epoch)
        self.assertTrue(old.closed)
        self.assertFalse(old.is_valid())
        self.assertFalse(old.is_superseded())
        self.assertFalse(old.supersede("late_input"))
        self.assertEqual(old.supersede_reason, "")
        with self.assertRaises(RunClosedError):
            old.raise_if_invalid()
        with self.assertRaises(RunClosedError):
            old.mark_action_started()
        self.assertFalse(old.action_started)
        self.assertTrue(current.is_valid())

    def test_current_does_not_create_or_advance_a_run(self) -> None:
        self.assertIsNone(self.control.current("lane-1"))
        self.assertIsNone(self.control.current("lane-1"))
        handle = self.control.begin("lane-1", self.trigger)
        self.assertIs(self.control.current("lane-1"), handle)
        self.assertEqual(handle.epoch, 1)
        self.assertFalse(handle.is_superseded())

    def test_new_controllers_have_no_shared_active_runs(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        other_control = RunControl()
        self.assertIsNone(other_control.current("lane-1"))
        other = other_control.begin("lane-1", self.trigger)
        self.assertEqual(other.epoch, 1)
        other_control.finish(handle)
        self.assertIs(other_control.current("lane-1"), other)
        self.assertFalse(handle.closed)
        handle.raise_if_invalid()
        other_control.supersede("lane-1", other.run_id)
        self.assertFalse(handle.is_superseded())

    def test_handle_raises_a_distinct_supersession_signal(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        self.assertTrue(handle.supersede("new_input"))
        self.assertFalse(handle.supersede("another_input"))
        with self.assertRaises(RunSupersededError) as caught:
            handle.raise_if_invalid()
        self.assertEqual(str(caught.exception), "new_input")
        self.assertNotIsInstance(caught.exception, asyncio.CancelledError)

    def test_action_start_is_retained_in_read_only_snapshots_after_supersession(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        before = handle.view()
        handle.mark_action_started()
        self.assertFalse(before.action_started)
        self.assertTrue(handle.view().action_started)
        self.control.supersede("lane-1", handle.run_id)
        self.control.begin("lane-1", self.trigger)
        self.assertTrue(handle.view().action_started)
        with self.assertRaises(RunSupersededError):
            handle.mark_action_started()

    def test_superseded_run_cannot_start_an_action(self) -> None:
        handle = self.control.begin("lane-1", self.trigger)
        self.control.supersede("lane-1", handle.run_id)
        self.control.begin("lane-1", self.trigger)
        with self.assertRaises(RunSupersededError):
            handle.mark_action_started()
        self.assertFalse(handle.view().action_started)

    def test_control_does_not_retain_the_trigger_or_message(self) -> None:
        event = RuntimeInput("lane-1", "private input")
        trigger = RunTrigger(RunKind.USER, event, now=10.0)
        event_ref, trigger_ref = weakref.ref(event), weakref.ref(trigger)
        handle = self.control.begin("lane-1", trigger)
        del event, trigger
        self.assertIsNone(event_ref())
        self.assertIsNone(trigger_ref())
        self.assertIs(self.control.current("lane-1"), handle)

    def test_finished_lanes_do_not_retain_identity_objects(self) -> None:
        class Lane(str):
            pass

        refs = []
        for index in range(100):
            lane = Lane(f"transient-{index}")
            refs.append(weakref.ref(lane))
            handle = self.control.begin(lane, self.trigger)
            self.control.finish(handle)
        del handle, lane
        gc.collect()
        self.assertTrue(all(ref() is None for ref in refs))


class RunSupersessionTest(unittest.IsolatedAsyncioTestCase):
    async def test_supersession_notifies_observers_without_cancelling_started_work(self) -> None:
        control = RunControl()
        trigger = RunTrigger(RunKind.DEFERRED, None, now=10.0)
        old = control.begin("lane-1", trigger)
        started, release = asyncio.Event(), asyncio.Event()

        async def action() -> str:
            old.mark_action_started()
            started.set()
            await release.wait()
            return "observed_result"

        running = asyncio.create_task(action())
        waiting = asyncio.create_task(old.superseded.wait())
        await started.wait()
        control.supersede("lane-1", old.run_id)
        current = control.begin("lane-1", trigger)
        self.assertTrue(await asyncio.wait_for(waiting, timeout=1.0))
        self.assertFalse(current.is_superseded())
        self.assertFalse(running.done())
        release.set()
        self.assertEqual(await running, "observed_result")
        control.finish(old)
        self.assertTrue(old.closed)
        self.assertTrue(old.action_started)
        self.assertIs(control.current("lane-1"), current)

    async def test_finish_blocks_new_actions_without_cancelling_started_work(self) -> None:
        control = RunControl()
        old = control.begin("lane-1", RunTrigger(RunKind.DEFERRED, None, now=10.0))
        started, release = asyncio.Event(), asyncio.Event()

        async def action() -> str:
            old.mark_action_started()
            started.set()
            await release.wait()
            return "observed_result"

        running = asyncio.create_task(action())
        await started.wait()
        control.finish(old)
        self.assertTrue(old.closed)
        self.assertFalse(old.is_superseded())
        self.assertTrue(old.view().action_started)
        self.assertFalse(running.done())
        with self.assertRaises(RunClosedError):
            old.mark_action_started()
        release.set()
        self.assertEqual(await running, "observed_result")


if __name__ == "__main__":
    unittest.main()
