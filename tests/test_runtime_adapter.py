"""AstrBot runtime adapter tests without importing AstrBot."""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.astrbot_model import AstrBotModelGateway  # noqa: E402
from adapters.astrbot_runtime import AstrBotRuntimeAdapter  # noqa: E402
from app.runtime import WakeAction, RunDecision  # noqa: E402
from core.source import make_source_id  # noqa: E402


class Event:
    def __init__(self, private: bool) -> None:
        self.private = private
        self.extras = {}
        self.created_at = 0.0
        self.unified_msg_origin = "bot:GroupMessage:g1"

    def is_private_chat(self) -> bool:
        return self.private

    def get_sender_id(self) -> str:
        return "u1"

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value) -> None:
        self.extras[key] = value


class AdapterTest(unittest.TestCase):
    def test_private_event_maps_to_direct_input(self) -> None:
        result = AstrBotRuntimeAdapter.from_event(
            Event(True), "hello?", "s1", "u1", unread_count=3
        )
        self.assertTrue(result.private)
        self.assertTrue(result.mentioned)
        self.assertTrue(result.question)
        self.assertEqual(result.unread_count, 3)

    def test_source_event_time_parses_iso_and_defaults_to_zero(self) -> None:
        self.assertEqual(
            AstrBotRuntimeAdapter.source_event_time(
                {"at": "1970-01-01T00:00:10+00:00"}
            ),
            10.0,
        )
        self.assertEqual(AstrBotRuntimeAdapter.source_event_time({}), 0.0)
        self.assertEqual(
            AstrBotRuntimeAdapter.source_event_time({"at": "not-a-time"}), 0.0
        )

    def test_event_timestamp_and_unread_watermark_are_mapped(self) -> None:
        event = Event(False)
        event.created_at = 123.5
        result = AstrBotRuntimeAdapter.from_event(
            event, "ambient", "g1", "u1", unread_count=4, unread_seq=9
        )
        self.assertEqual(result.event_time, 123.5)
        self.assertEqual(result.unread_count, 4)
        self.assertEqual(result.unread_seq, 9)

    def test_invalid_timestamp_and_negative_watermarks_are_clamped(self) -> None:
        event = Event(False)
        event.created_at = "not-a-timestamp"
        result = AstrBotRuntimeAdapter.from_event(
            event, "ambient", "g1", "u1", unread_count=-3, unread_seq=-2
        )
        self.assertEqual(result.event_time, 0.0)
        self.assertEqual(result.unread_count, 0)
        self.assertEqual(result.unread_seq, 0)

    def test_group_event_is_not_direct(self) -> None:
        result = AstrBotRuntimeAdapter.from_event(
            Event(False), "ambient", "g1", "u1"
        )
        self.assertFalse(result.private)
        self.assertFalse(result.mentioned)
        self.assertFalse(result.question)

    def test_wake_command_marks_group_message_as_direct(self) -> None:
        event = Event(False)
        event.is_at_or_wake_command = True
        result = AstrBotRuntimeAdapter.from_event(event, "hello", "g1", "u1")
        self.assertTrue(result.mentioned)

    def test_model_gateway_resolves_provider_and_returns_text(self) -> None:
        class Provider:
            async def text_chat(self, prompt, system_prompt=None):
                self.prompt = prompt
                self.system_prompt = system_prompt
                return SimpleNamespace(completion_text="  reply  ")

        class Context:
            def __init__(self):
                self.provider = Provider()

            async def get_using_provider_async(self, session_id):
                self.session_id = session_id
                return self.provider

        context = Context()
        text = asyncio.run(
            AstrBotModelGateway(context).complete("s1", "hello", "memory")
        )
        self.assertEqual(text, "reply")
        self.assertEqual(context.session_id, "s1")
        self.assertEqual(context.provider.prompt, "hello")
        self.assertEqual(context.provider.system_prompt, "memory")

    def test_model_gateway_reports_missing_provider(self) -> None:
        class Context:
            async def get_using_provider_async(self, session_id):
                return None

        with self.assertRaises(RuntimeError):
            asyncio.run(AstrBotModelGateway(Context()).complete("s1", "hello"))

    def test_reply_turn_id_preserves_legacy_fallback(self) -> None:
        event = Event(False)
        expected = make_source_id(
            session_id="bot:GroupMessage:g1",
            speaker_id="u1",
            role="assistant",
            text="ok",
        )
        self.assertEqual(
            AstrBotRuntimeAdapter.reply_turn_id(event, "ok"), expected
        )
        event.set_extra("_seekmemory_turn_id", "turn-1")
        self.assertEqual(AstrBotRuntimeAdapter.reply_turn_id(event, "ok"), "turn-1")

    def test_decision_is_exposed_as_event_metadata(self) -> None:
        event = Event(False)
        AstrBotRuntimeAdapter.apply_decision(
            event, RunDecision(WakeAction.OBSERVE, "ambient_message")
        )
        self.assertEqual(event.extras["_seekmemory_runtime_action"], "observe")
        self.assertEqual(event.extras["_seekmemory_runtime_reason"], "ambient_message")


if __name__ == "__main__":
    unittest.main()
