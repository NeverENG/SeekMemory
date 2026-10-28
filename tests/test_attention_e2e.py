"""Host event -> RuntimeInput -> default attention decision."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.astrbot.events import to_runtime_input
from app.runtime.attention import DefaultAttentionPolicy
from app.runtime.contracts import SessionState, WakeAction


class At:
    def __init__(self, qq: str) -> None:
        self.qq = qq


class FakeAstrBotEvent:
    def __init__(self, **kw) -> None:
        self.message_str = kw.get("text", "")
        self.is_at_or_wake_command = kw.get("wake_all", kw.get("mentioned", False))
        self._at_me = kw.get("at_me", kw.get("mentioned", False))
        self._at_other = kw.get("at_other", False)
        self.sender_id = kw.get("sender_id", "10001")
        self.group_id = kw.get("group_id", "7001")
        self.thread_id = kw.get("thread_id", "")
        self.self_id = kw.get("self_id", "bot-1")
        self.created_at = kw.get("created_at", 1000.0)
        self.unified_msg_origin = kw.get("umo", "napcat:GroupMessage:7001")
        self.message_id = kw.get("message_id", "m1")
        self.reply_to_self = kw.get("reply_to_self", False)
        self.role = kw.get("role", "")
        self.scene = kw.get("scene", "")
        self._private = kw.get("private", False)

    def get_messages(self):
        if self._at_me:
            return [At(self.self_id)]
        if self._at_other:
            return [At("someone-else")]
        return []

    def is_private_chat(self) -> bool:
        return self._private


OWNER = "owner-1"


class EndToEndPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DefaultAttentionPolicy()

    def decide(self, event: FakeAstrBotEvent, state: SessionState | None = None):
        mapped = to_runtime_input(
            event, session_id=event.unified_msg_origin, owner_id=OWNER
        )
        return mapped, self.policy.evaluate(
            mapped, state or SessionState("s"), 1000.0
        )

    def test_wake_all_is_not_a_mention(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="随便聊聊", wake_all=True)
        )
        self.assertFalse(mapped.mentioned)
        self.assertFalse(mapped.addressed)
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_at_other_is_not_a_mention(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="@别人 你看", at_other=True)
        )
        self.assertFalse(mapped.mentioned)
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_private_message_maps_and_replies(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(
                text="在吗", private=True, umo="napcat:FriendMessage:owner-1"
            )
        )
        self.assertEqual(mapped.scene, "private")
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "private_message")

    def test_group_mention_maps_to_direct_attention(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="大肥鱼在吗", mentioned=True)
        )
        self.assertEqual(mapped.scene, "group")
        self.assertTrue(mapped.addressed)
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")

    def test_owner_in_group_maps_role_and_replies(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="今天好累", sender_id=OWNER)
        )
        self.assertEqual(mapped.role, "owner")
        self.assertTrue(mapped.is_owner)
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "owner")

    def test_unaddressed_group_message_observes(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="大家好", sender_id="88888")
        )
        self.assertEqual(mapped.role, "member")
        self.assertIs(decision.action, WakeAction.OBSERVE)
        self.assertEqual(decision.reason, "ambient_message")

    def test_comment_thread_is_preserved_without_platform_branching(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(
                text="这条视频不错",
                scene="comment",
                thread_id="thread-9",
                umo="bilibili:Comment:thread-9",
            )
        )
        self.assertEqual(mapped.scene, "comment")
        self.assertEqual(mapped.thread_id, "thread-9")
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_name_call_counts_as_addressed(self) -> None:
        event = FakeAstrBotEvent(text="大肥鱼你在干嘛", sender_id="user-1")
        mapped = to_runtime_input(
            event,
            session_id=event.unified_msg_origin,
            owner_id=OWNER,
            names=("大肥鱼",),
        )
        self.assertTrue(mapped.addressed)
        decision = self.policy.evaluate(mapped, SessionState("s"), 1000.0)
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")


if __name__ == "__main__":
    unittest.main()
