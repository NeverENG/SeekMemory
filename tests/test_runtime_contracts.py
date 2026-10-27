"""Pure contracts for the host-neutral AgentRuntime."""

from __future__ import annotations

import os
import sys
import unittest
from dataclasses import fields

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    ActionKind,
    ActionRecord,
    ActionStatus,
    MemoryContextRequest,
    ProactiveDecision,
    RuntimeInput,
    SessionState,
)


class RuntimeContractsTest(unittest.TestCase):
    def test_runtime_input_keeps_event_and_receipt_time_separate(self) -> None:
        event = RuntimeInput(
            "s1", "hello", event_time=100.0, received_at=102.5
        )
        self.assertEqual(event.event_time, 100.0)
        self.assertEqual(event.received_at, 102.5)

    def test_action_record_has_no_content_fields_and_has_terminal_state(self) -> None:
        names = {field.name for field in fields(ActionRecord)}
        self.assertFalse(
            {"text", "prompt", "arguments", "result", "message"} & names
        )
        record = ActionRecord(
            action_id="a1",
            session_id="s1",
            kind=ActionKind.TOOL_CALL,
            status=ActionStatus.SUCCEEDED,
        )
        self.assertTrue(record.terminal)
        attempted = ActionRecord(action_id="a2", session_id="s1")
        self.assertFalse(attempted.terminal)

    def test_session_state_has_proactive_and_action_defaults(self) -> None:
        state = SessionState(session_id="s1")
        self.assertEqual(state.proactive_due_at, 0.0)
        self.assertEqual(state.proactive_attempts, 0)
        self.assertEqual(state.last_action_status, "")

    def test_proactive_decision_and_memory_request_are_host_neutral(self) -> None:
        decision = ProactiveDecision(should_speak=True, reason="due", due_at=20.0)
        request = MemoryContextRequest(
            session_id="s1",
            query="hello",
            event_time=10.0,
            received_at=11.0,
            now=12.0,
            reason="inbound",
        )
        self.assertTrue(decision.should_speak)
        self.assertEqual(request.query, "hello")
        self.assertEqual(request.now, 12.0)


if __name__ == "__main__":
    unittest.main()
