"""Shared nonempty Node/Python wire examples checked against authoritative DTOs."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.astrbot.runtime import AstrBotRuntimeAdapter  # noqa: E402
from adapters.astrbot.events import to_runtime_input  # noqa: E402
from app.runtime import (  # noqa: E402
    ActionRequest, ActionResult, MemoryContext, MemoryContextRequest, RunDecision,
    RunResult, RuntimeInput, UserRunReceipt,
)
from app.runtime.recorder import RecordedReply  # noqa: E402

FIXTURE = json.loads((ROOT / "tests/fixtures/runtime_host.json").read_text(encoding="utf-8"))


class RuntimeHostContractTest(unittest.TestCase):
    def test_shared_examples_match_complete_public_dto_shapes(self):
        for key, dto in (
            ("input", RuntimeInput), ("context_request", MemoryContextRequest),
            ("context", MemoryContext), ("action_request", ActionRequest),
            ("action_result", ActionResult), ("reply", RecordedReply), ("run_result", RunResult),
        ):
            with self.subTest(key=key):
                self.assertEqual(asdict(dto(**FIXTURE[key])), FIXTURE[key])
        receipt = dict(FIXTURE["receipt"])
        receipt["decision"] = RunDecision(**receipt["decision"])
        self.assertEqual(asdict(UserRunReceipt(**receipt)), FIXTURE["receipt"])

    def test_astrbot_maps_the_same_event_as_the_node_example(self):
        data = FIXTURE["input"]
        class At:
            def __init__(self, qq: str) -> None:
                self.qq = qq

        event = SimpleNamespace(
            created_at=data["event_time"], is_private_chat=lambda: False,
            is_at_or_wake_command=True, message_id=data["event_id"],
            get_messages=lambda: [At(data["self_id"])],
        )
        mapped = AstrBotRuntimeAdapter.from_event(
            event, data["text"], data["session_id"], data["speaker_id"],
            received_at=data["received_at"],
        )
        self.assertEqual(asdict(mapped), data)

    def test_runtime_adapter_reuses_owner_scene_and_name_mapping(self):
        event = SimpleNamespace(
            message_str="大肥鱼在吗", sender_id="owner-1", group_id="group-1", self_id="bot-1",
            message_obj=SimpleNamespace(message_id="event-2"), scene="thread", thread_id="thread-1",
            reply_to_self=True, created_at=10, is_private_chat=lambda: False,
        )
        shared = to_runtime_input(event, session_id="session", owner_id="owner-1",
                                  names=("大肥鱼",), received_at=12)
        mapped = AstrBotRuntimeAdapter.from_event(
            event, event.message_str, "session", "owner-1", owner_id="owner-1",
            names=("大肥鱼",), received_at=12,
        )
        self.assertEqual(mapped, shared)
        self.assertTrue(mapped.is_owner)
        self.assertTrue(mapped.addressed)
        self.assertEqual(mapped.event_id, "event-2")

    def test_malformed_host_times_and_counts_do_not_poison_runtime_state(self):
        for value in ("not-a-time", float("nan"), float("inf"), -1):
            event = SimpleNamespace(created_at=value, is_private_chat=lambda: False)
            mapped = AstrBotRuntimeAdapter.from_event(
                event, "hello", "session", "speaker", unread_count="bad", unread_seq=True,
            )
            self.assertEqual(mapped.event_time, 0)
            self.assertEqual((mapped.unread_count, mapped.unread_seq), (0, 0))


if __name__ == "__main__":
    unittest.main()
