"""开口策略、场景提示与话题候选的纯函数回归测试。"""

from __future__ import annotations

import unittest

from app.runtime.attention import AttentionPolicy, AttentionThresholds, preset, thresholds_from_config
from app.runtime.contracts import RuntimeInput, SessionState, WakeAction
from app.runtime.scene_hints import compose, time_window
from app.runtime.signals import Signals
from app.runtime.topics import TopicCandidate, rank, usable


def event(**overrides) -> RuntimeInput:
    base = dict(session_id="napcat:GroupMessage:1", text="今天好累", scene="group")
    base.update(overrides)
    return RuntimeInput(**base)


class AttentionPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = AttentionPolicy()

    def test_empty_text_is_ignored(self) -> None:
        decision = self.policy.decide(event(text="  "), SessionState("s"), Signals(), 100.0)
        self.assertIs(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "empty_text")

    def test_private_message_always_replies(self) -> None:
        decision = self.policy.decide(
            event(private=True, text="在吗"), SessionState("s"), Signals(), 100.0
        )
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertTrue(decision.must_reply)

    def test_mention_and_reply_attention_are_hard_rules(self) -> None:
        for kwargs in ({"mentioned": True}, {"reply_to_me": True}, {"addressed": True}):
            decision = self.policy.decide(event(**kwargs), SessionState("s"), Signals(), 100.0)
            self.assertIs(decision.action, WakeAction.REPLY)
            self.assertTrue(decision.must_reply, kwargs)

    def test_owner_replies_but_respects_cooldown(self) -> None:
        state = SessionState("s", last_spoke_at=95.0)
        decision = self.policy.decide(
            event(role="owner"), state, Signals(), 100.0
        )
        self.assertIs(decision.action, WakeAction.WAIT)
        self.assertEqual(decision.reason, "owner_cooldown")

        fresh = SessionState("s", last_spoke_at=0.0)
        decision = self.policy.decide(event(role="owner"), fresh, Signals(), 100.0)
        self.assertIs(decision.action, WakeAction.REPLY)

    def test_stranger_ambient_is_observed_not_replied(self) -> None:
        decision = self.policy.decide(
            event(role="member"), SessionState("s"), Signals(heat=0.1), 100.0
        )
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_relevant_question_replies(self) -> None:
        decision = self.policy.decide(
            event(role="member", question=True), SessionState("s"),
            Signals(relevance=0.8), 100.0,
        )
        self.assertIs(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "relevant_question")

    def test_irrelevant_question_stays_quiet(self) -> None:
        decision = self.policy.decide(
            event(role="member", question=True), SessionState("s"),
            Signals(relevance=0.0), 100.0,
        )
        self.assertIs(decision.action, WakeAction.OBSERVE)

    def test_quiet_window_blocks_ambient_but_not_direct(self) -> None:
        state = SessionState("s", quiet_until=200.0)
        quiet = self.policy.decide(event(role="member"), state, Signals(), 100.0)
        self.assertIs(quiet.action, WakeAction.IGNORE)
        direct = self.policy.decide(event(mentioned=True), state, Signals(), 100.0)
        self.assertIs(direct.action, WakeAction.REPLY)

    def test_stranger_quota_scales_with_relationship(self) -> None:
        thresholds = AttentionThresholds()
        self.assertEqual(self.policy.stranger_quota(Signals(relationship=0.0)), thresholds.stranger_quota_base)
        self.assertEqual(self.policy.stranger_quota(Signals(relationship=0.4)), thresholds.stranger_quota_familiar)
        self.assertEqual(self.policy.stranger_quota(Signals(relationship=0.9)), thresholds.stranger_quota_close)

    def test_hot_room_waits(self) -> None:
        decision = self.policy.decide(
            event(role="member"), SessionState("s"), Signals(heat=0.9), 100.0
        )
        self.assertIs(decision.action, WakeAction.WAIT)
        self.assertEqual(decision.reason, "hot_room")


class PresetTest(unittest.TestCase):
    def test_presets_scale_friendliness(self) -> None:
        self.assertEqual(preset("quiet").stranger_quota_base, 0)
        self.assertEqual(preset("balanced").stranger_quota_base, 2)
        self.assertEqual(preset("chatty").stranger_quota_base, 2)
        self.assertGreater(preset("chatty").relevance_reply, 0)
        self.assertLess(preset("chatty").relevance_reply, preset("balanced").relevance_reply)

    def test_unknown_preset_falls_back_to_balanced(self) -> None:
        self.assertEqual(preset("nope").relevance_reply, preset("balanced").relevance_reply)

    def test_config_overrides_preset_fields(self) -> None:
        conf = lambda key, default: (
            "chatty" if key == "attention_preset"
            else ('{"heat_wait": 0.95}' if key == "attention_thresholds" else default)
        )
        thresholds = thresholds_from_config(conf)
        self.assertAlmostEqual(thresholds.heat_wait, 0.95)
        self.assertAlmostEqual(thresholds.relevance_reply, preset("chatty").relevance_reply)

    def test_bad_threshold_json_falls_back(self) -> None:
        conf = lambda key, default: "not-json" if key == "attention_thresholds" else default
        self.assertEqual(thresholds_from_config(conf).relevance_reply, preset("balanced").relevance_reply)


class SceneHintsTest(unittest.TestCase):
    def test_time_windows(self) -> None:
        self.assertEqual(time_window(3), "late")
        self.assertEqual(time_window(9), "day")
        self.assertEqual(time_window(21), "evening")

    def test_private_hint_skips_closeness(self) -> None:
        text = compose(event(private=True), Signals(relationship=0.0), 21)
        self.assertIn("私聊", text)
        self.assertNotIn("几乎没有印象", text)

    def test_group_owner_and_stranger_hints(self) -> None:
        owner = compose(event(role="owner"), Signals(relationship=0.8), 9)
        self.assertIn("主人", owner)
        stranger = compose(event(role="member"), Signals(relationship=0.0), 21)
        self.assertIn("其他人", stranger)
        self.assertIn("几乎没有印象", stranger)


class TopicsTest(unittest.TestCase):
    def test_rank_sorts_by_score(self) -> None:
        items = [
            TopicCandidate("a", score=0.2),
            TopicCandidate("b", score=0.9),
            TopicCandidate("c", score=0.5),
        ]
        self.assertEqual([t.text for t in rank(items, 2)], ["b", "c"])

    def test_usable_filters_cooldown_ids(self) -> None:
        candidate = TopicCandidate("还记得那件事吗", memory_ids=("m1",))
        self.assertFalse(usable(candidate, {"m1"}))
        self.assertTrue(usable(candidate, {"m2"}))


class RuntimeInputCompatTest(unittest.TestCase):
    def test_old_construction_still_works(self) -> None:
        value = RuntimeInput(session_id="s", text="hi")
        self.assertFalse(value.scene)
        self.assertEqual(value.kind, "message")
        self.assertFalse(value.is_owner)

    def test_new_fields_are_optional(self) -> None:
        value = RuntimeInput(
            session_id="s", text="hi", scene="group", role="owner",
            conversation_id="123", addressed=True,
        )
        self.assertTrue(value.is_owner)
        self.assertEqual(value.conversation_id, "123")


if __name__ == "__main__":
    unittest.main()
