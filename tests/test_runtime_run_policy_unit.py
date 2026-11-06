"""Pure same-lane run policy decisions."""

from __future__ import annotations

import sys
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.contracts import ActiveRunView, RunKind, RunTrigger, RuntimeInput, SessionState  # noqa: E402
from app.runtime.policy.runs import DefaultRunPolicy  # noqa: E402


class DefaultRunPolicyTest(unittest.TestCase):
    def test_idle_lane_admits_each_run_kind(self) -> None:
        state = SessionState("s1")
        for kind in RunKind:
            with self.subTest(kind=kind):
                result = DefaultRunPolicy().decide(state, RunTrigger(kind, None, 10.0), None)
                self.assertTrue(result.start_new)
                self.assertFalse(result.supersede_active)

    def test_user_supersedes_while_background_work_preserves_active_run(self) -> None:
        state = SessionState("s1", followup_by_speaker={"u1": 2})
        before = asdict(state)
        for active_kind in RunKind:
            for kind in RunKind:
                with self.subTest(active=active_kind, trigger=kind):
                    active = ActiveRunView("r1", "s1", 1, active_kind, 9.0)
                    event = RuntimeInput("s1", "hello") if kind is RunKind.USER else None
                    result = DefaultRunPolicy().decide(state, RunTrigger(kind, event, 10.0), active)
                    self.assertEqual(result.start_new, kind is RunKind.USER)
                    self.assertEqual(result.supersede_active, kind is RunKind.USER)
        self.assertEqual(asdict(state), before)


if __name__ == "__main__":
    unittest.main()
