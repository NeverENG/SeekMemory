"""Pure run contracts for custom policies; no host or storage fixtures."""

from __future__ import annotations

import inspect
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import get_type_hints

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime.contracts import (  # noqa: E402
    ActiveRunView,
    RunKind,
    RunPolicy,
    RunTransition,
    RunTrigger,
    RuntimeInput,
    SessionState,
)


class RunContractsTest(unittest.TestCase):
    def test_user_and_background_triggers_use_host_neutral_inputs(self) -> None:
        event = RuntimeInput("s1", "hello", mentioned=True)
        trigger = RunTrigger(RunKind.USER, event, now=12.0)
        self.assertIs(trigger.event, event)
        self.assertEqual(trigger.now, 12.0)
        for value in ("user", "deferred", "proactive"):
            kind = RunKind(value)
            self.assertEqual(kind, value)
            if kind is not RunKind.USER:
                self.assertIsNone(RunTrigger(kind, None, now=12.0).event)

    def test_policy_values_are_immutable(self) -> None:
        values = (
            (RunTrigger(RunKind.DEFERRED, None, now=12.0), "now", 13.0),
            (ActiveRunView("r1", "lane-1", 1, RunKind.USER, started_at=10.0), "epoch", 2),
            (RunTransition(), "supersede_active", True),
        )
        for value, field, replacement in values:
            with self.subTest(contract=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, field, replacement)

    def test_custom_policy_needs_only_contract_objects(self) -> None:
        self.assertFalse(inspect.iscoroutinefunction(RunPolicy.decide))
        self.assertEqual(get_type_hints(RunPolicy.decide), {
            "state": SessionState,
            "trigger": RunTrigger,
            "active": ActiveRunView | None,
            "return": RunTransition,
        })

        class ReplaceOnUserPolicy:
            def decide(
                self,
                state: SessionState,
                trigger: RunTrigger,
                active: ActiveRunView | None,
            ) -> RunTransition:
                if active is None:
                    return RunTransition()
                if trigger.kind is RunKind.USER:
                    return RunTransition(supersede_active=True)
                return RunTransition(start_new=False)

        policy: RunPolicy = ReplaceOnUserPolicy()
        state = SessionState("s1")
        trigger = RunTrigger(RunKind.USER, RuntimeInput("s1", "hello"), now=12.0)
        self.assertEqual(policy.decide(state, trigger, None), RunTransition())
        active = ActiveRunView("r1", "s1", 1, RunKind.USER, started_at=10.0)
        self.assertEqual(
            policy.decide(state, trigger, active),
            RunTransition(supersede_active=True),
        )
        self.assertEqual(
            policy.decide(state, RunTrigger(RunKind.PROACTIVE, None, now=12.0), active),
            RunTransition(start_new=False),
        )


if __name__ == "__main__":
    unittest.main()
