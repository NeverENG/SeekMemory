"""端到端策略测试：宿主事件 → RuntimeInput → 决策。

用假的 AstrBot 事件对象走真实映射函数（adapters/astrbot_event.py），
验证"该不该回"整条链路，不依赖宿主运行时。这是 #123 验收的一部分；
#116 合入后同一套夹具可换成真宿主边界。
"""

from __future__ import annotations

import unittest

from adapters.astrbot_event import to_runtime_input
from app.runtime.attention import AttentionPolicy, thresholds_from_config
from app.runtime.contracts import SessionState, WakeAction
from app.runtime.scene_hints import compose
from app.runtime.signals import Signals


class FakeAstrBotEvent:
    """最小 AstrBot 事件表面：只提供映射需要的字段。"""

    def __init__(self, **kw) -> None:
        self.message_str = kw.get("text", "")
        self.is_at_or_wake_command = kw.get("mentioned", False)
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

    def is_private_chat(self) -> bool:
        return self._private


OWNER = "owner-1"


class EndToEndPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AttentionPolicy()

    def decide(self, event: FakeAstrBotEvent, signals: Signals | None = None,
               state: SessionState | None = None, now: float = 1000.0):
        mapped = to_runtime_input(event, session_id=event.unified_msg_origin, owner_id=OWNER)
        return mapped, self.policy.decide(mapped, state or SessionState("s"), signals or Signals(), now)

    def test_private_message_maps_and_replies(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="在吗", private=True, umo="napcat:FriendMessage:owner-1")
        )
        self.assertEqual(mapped.scene, "private")
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "private_message")

    def test_group_mention_replies(self) -> None:
        mapped, decision = self.decide(FakeAstrBotEvent(text="大肥鱼在吗", mentioned=True))
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

    def test_stranger_in_group_stays_quiet(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(text="大家好", sender_id="88888"),
            signals=Signals(heat=0.1),
        )
        self.assertEqual(mapped.role, "member")
        self.assertIs(decision.action, WakeAction.OBSERVE)
        self.assertEqual(decision.reason, "ambient_message")

    def test_comment_scene_keeps_thread(self) -> None:
        mapped, decision = self.decide(
            FakeAstrBotEvent(
                text="这条视频不错", private=False, scene="comment",
                thread_id="thread-9", umo="bilibili:Comment:thread-9",
            )
        )
        self.assertEqual(mapped.scene, "comment")
        self.assertEqual(mapped.thread_id, "thread-9")
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_scene_hint_renders_for_mapped_event(self) -> None:
        event = FakeAstrBotEvent(text="我回来啦", sender_id=OWNER)
        mapped = to_runtime_input(event, session_id=event.unified_msg_origin, owner_id=OWNER)
        text = compose(mapped, Signals(relationship=0.8), 21)
        self.assertIn("主人", text)
        self.assertIn("晚上", text)

    def test_thresholds_from_config_round_trip(self) -> None:
        conf = lambda key, default: '{"relevance_reply": 0.6, "stranger_quota_close": 6}' if key == "attention_thresholds" else default
        thresholds = thresholds_from_config(conf)
        self.assertAlmostEqual(thresholds.relevance_reply, 0.6)
        self.assertEqual(thresholds.stranger_quota_close, 6)


if __name__ == "__main__":
    unittest.main()
