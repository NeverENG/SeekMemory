"""Default host-neutral attention policy regressions."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime.attention import DefaultAttentionPolicy
from app.runtime.contracts import RuntimeInput, SessionState, WakeAction


def event(**overrides) -> RuntimeInput:
    base = dict(session_id="session-1", text="hello", speaker_id="u1")
    base.update(overrides)
    return RuntimeInput(**base)


class OwnerAndFollowupTest(unittest.TestCase):
    def test_owner_off_falls_back_to_ambient(self) -> None:
        policy = DefaultAttentionPolicy(owner_always_reply=False)
        decision = policy.evaluate(
            event(role="owner"), SessionState("s"), 0.0
        )
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_owner_private_still_replies_when_owner_switch_is_off(self) -> None:
        policy = DefaultAttentionPolicy(owner_always_reply=False)
        decision = policy.evaluate(
            event(role="owner", private=True), SessionState("s"), 0.0
        )
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "private_message")

    def test_followup_rounds_come_from_config(self) -> None:
        policy = DefaultAttentionPolicy(followup_rounds=2)
        state = SessionState("s")
        state.followup_by_speaker = {"u1": 2}
        decision = policy.evaluate(event(speaker_id="u1"), state, 0.0)
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "followup")
        self.assertEqual(decision.followup_remaining, 1)


class DefaultAttentionPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DefaultAttentionPolicy()
        self.state = SessionState("session-1")

    def test_empty_text_is_ignored(self) -> None:
        decision = self.policy.evaluate(event(text="  "), self.state, 100.0)
        self.assertIs(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "empty_text")

    def test_owner_always_replies(self) -> None:
        decision = self.policy.evaluate(
            event(role="owner"), self.state, 100.0
        )
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "owner")
        self.assertTrue(decision.must_reply)

    def test_private_always_replies(self) -> None:
        decision = self.policy.evaluate(
            event(private=True), self.state, 100.0
        )
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "private_message")
        self.assertTrue(decision.must_reply)

    def test_direct_attention_sets_three_followup_rounds(self) -> None:
        for flags in (
            {"mentioned": True},
            {"addressed": True},
            {"reply_to_me": True},
        ):
            decision = self.policy.evaluate(
                event(**flags), SessionState("session-1"), 100.0
            )
            self.assertIs(decision.action, WakeAction.REPLY)
            self.assertEqual(decision.reason, "direct_attention")
            self.assertEqual(decision.followup_speaker_id, "u1")
            self.assertEqual(decision.followup_remaining, 3)

    def test_followup_is_per_speaker(self) -> None:
        self.state.followup_by_speaker = {"u1": 2}
        first = self.policy.evaluate(event(), self.state, 100.0)
        other = self.policy.evaluate(
            event(speaker_id="u2"), self.state, 100.0
        )
        self.assertIs(first.action, WakeAction.REPLY)
        self.assertEqual(first.reason, "followup")
        self.assertEqual(first.followup_speaker_id, "u1")
        self.assertEqual(first.followup_remaining, 1)
        self.assertIs(other.action, WakeAction.OBSERVE)

    def test_unaddressed_ambient_message_is_observed(self) -> None:
        decision = self.policy.evaluate(event(), self.state, 100.0)
        self.assertIs(decision.action, WakeAction.OBSERVE)
        self.assertEqual(decision.reason, "ambient_message")


class FollowupStateTest(unittest.TestCase):
    def test_agent_runtime_applies_followup_patch(self) -> None:
        from app.runtime import AgentRuntime, InMemoryStateStore

        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100.0)
        runtime.observe(event(mentioned=True), now=100.0)
        state = store.get("session-1")
        self.assertEqual(state.followup_by_speaker["u1"], 3)

        runtime.observe(event(), now=101.0)
        self.assertEqual(store.get("session-1").followup_by_speaker["u1"], 2)

    def test_agent_runtime_bounds_followup_speaker_map(self) -> None:
        from app.runtime import AgentRuntime, InMemoryStateStore

        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100.0)
        for index in range(70):
            runtime.observe(
                event(speaker_id=f"u{index}", mentioned=True), now=100.0
            )
        self.assertLessEqual(len(store.get("session-1").followup_by_speaker), 64)

    def test_agent_runtime_clears_followup_at_zero(self) -> None:
        from app.runtime import AgentRuntime, InMemoryStateStore

        store = InMemoryStateStore()
        state = store.get("session-1")
        state.followup_by_speaker = {"u1": 1}
        store.put(state)
        runtime = AgentRuntime(store, clock=lambda: 100.0)
        runtime.observe(event(), now=100.0)
        self.assertNotIn("u1", store.get("session-1").followup_by_speaker)


if __name__ == "__main__":
    unittest.main()
