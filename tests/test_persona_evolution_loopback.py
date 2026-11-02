"""Successful extraction remains successful when persona maintenance fails."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from adapters.loopback.runtime import MemoryService

UMO = "lab:persona"


def _item(pair: tuple[str, str], text: str, behavior: str, confidence: float = 0.95) -> dict:
    """Build one deterministic extraction item citing its exact user/assistant pair."""
    user_sid, bot_sid = pair
    return {
        "level": "scene", "text": text, "tags": "lab persona behavior",
        "about": "relation", "subject_kind": "self", "subject_id": "self",
        "event_at": "2026-11-01T10:00:00", "confidence": confidence,
        "arousal": 0.2, "valence": 0, "funny": 0, "first": True,
        "bot_behavior": behavior, "bot_action": text,
        "evidence_source_ids": [user_sid, bot_sid],
    }


class _LoopbackCase(unittest.TestCase):
    """Share one isolated data directory and the real loopback service."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.gettempdir()) / f"sm-persona-loopback-{uuid4().hex}"
        self.tmp.mkdir()
        self.service = MemoryService(self.tmp, {"owner_umo": UMO,
                                               "persona_min_interval_s": 0}, quiet=True)

    def tearDown(self) -> None:
        self.service.store.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def exchange(self, user_text: str, bot_text: str,
                 items: list[dict]) -> tuple[int, dict]:
        """Capture one reply-paired turn, then commit the given behavior items."""
        code, user = self.service.capture({"subject_key": UMO, "role": "user",
                                           "text": user_text,
                                           "msg_id": f"u-{uuid4().hex}"})
        self.assertEqual(code, 200, user)
        code, bot = self.service.capture({"subject_key": UMO, "role": "assistant",
                                          "text": bot_text,
                                          "msg_id": f"a-{uuid4().hex}",
                                          "reply_to": user["source_id"]})
        self.assertEqual(code, 200, bot)
        code, plan = self.service.extract_plan({"subject_key": UMO})
        self.assertEqual(code, 200, plan)
        pair = (user["source_id"], bot["source_id"])
        payload = [_item(pair, item["text"], item["bot_behavior"],
                         item.get("confidence", 0.95)) for item in items]
        code, result = self.service.extract_commit({
            "task_id": plan["task_id"], "source_ids": plan["source_ids"],
            "chat_response": {"text": json.dumps(payload, ensure_ascii=False)},
        })
        self.assertEqual(code, 200, result)
        return code, result

    def persona(self) -> dict:
        code, body = self.service.persona({"subject_key": UMO})
        self.assertEqual(code, 200, body)
        return body

    def maintenance(self) -> dict:
        return self.service.status()[1]["persona_maintenance"]


class PersonaEvolutionLoopbackTest(unittest.TestCase):
    def test_maintenance_failure_does_not_change_committed_extraction(self) -> None:
        tmp = Path(tempfile.gettempdir()) / f"sm-persona-loopback-{uuid4().hex}"
        tmp.mkdir()
        try:
            service = MemoryService(tmp, {"owner_umo": "lab:persona"}, quiet=True)
            try:
                code, user = service.capture({
                    "subject_key": "lab:persona", "role": "user", "text": "明天去医院检查眼睛",
                })
                self.assertEqual(code, 200)
                code, plan = service.extract_plan({"subject_key": "lab:persona"})
                self.assertEqual(code, 200)
                item = {"level": "fact", "text": "明天去医院检查眼睛", "tags": "医院 检查 眼睛",
                        "about": "other", "subject_kind": "speaker", "subject_id": "user(owner)",
                        "event_at": "2026-11-01T10:00:00", "confidence": 0.95,
                        "arousal": 0.2, "valence": 0, "funny": 0, "first": True,
                        "evidence_source_ids": [user["source_id"]]}

                def fail() -> None:
                    raise RuntimeError("maintenance failed")

                service.persona_evolution.after_extraction = fail
                code, result = service.extract_commit({
                    "task_id": plan["task_id"], "source_ids": plan["source_ids"],
                    "chat_response": {"text": json.dumps([item], ensure_ascii=False)},
                })
                self.assertEqual(code, 200, result)
                self.assertEqual(result["written"], 1)
                self.assertTrue(service.persona_evolution.degraded)
                # The failure reason survives for operators instead of an empty field.
                self.assertIn("maintenance failed", service.status()[1]
                              ["persona_maintenance"]["last_error"])
                self.assertEqual(service.persona_evolution.failures, 1)
                self.assertEqual(service.extract_commit({"task_id": plan["task_id"]})[0], 409)
            finally:
                service.store.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class PersonaEvidenceAccountingTest(_LoopbackCase):
    """A legal no-op must stay legal, and must say which category is short."""

    def test_two_same_kind_observations_stay_below_gate(self) -> None:
        self.exchange("我被批评了", "委屈是真的，先缓一缓。",
                      [{"text": "她先回应情绪", "bot_behavior": "respond_emotion"}])
        self.exchange("我撑不住了", "我在，先把感受说出来。",
                      [{"text": "她先回应情绪", "bot_behavior": "respond_emotion"}])
        state = self.maintenance()
        self.assertEqual(state["evidence"], {"respond_emotion": 2})
        self.assertEqual(state["min_evidence"], 3)
        self.assertFalse(state["dirty"])
        self.assertFalse(state["degraded"])
        self.assertEqual(state["last_writes"], 0)
        self.assertEqual(self.persona()["revision"], 0)

    def test_third_same_kind_observation_promotes_persona(self) -> None:
        for index in range(3):
            self.exchange(f"我今天很难受{index}", "我在，先不急着解决。",
                          [{"text": "她先回应情绪", "bot_behavior": "respond_emotion"}])
            if index < 2:
                self.assertEqual(self.persona()["revision"], 0)
        state = self.maintenance()
        self.assertEqual(state["evidence"], {"respond_emotion": 3})
        self.assertEqual(state["last_writes"], 1)
        self.assertTrue(state["last_persona"])
        after = self.persona()
        self.assertGreaterEqual(after["revision"], 1)
        self.assertTrue(after["text"])

    def test_four_observations_across_three_categories_explain_the_no_op(self) -> None:
        """Replay the lab sample: 4 valid behaviors, but 2/1/1 per category."""
        self.exchange("要输入不输入的时候先憋着，我自己说",
                      "我记着，不该输入时我不越界，也不催。",
                      [{"text": "她保护隐私且不透露", "bot_behavior": "protect_privacy"}])
        self.exchange("先把这段跑一遍，然后读 HANDOVER.md",
                      "在，但当前会话没有可参考的上下文，我不编。",
                      [{"text": "她承认不确定", "bot_behavior": "admit_uncertainty"}])
        self.exchange("那个你看清弄吧，我不太确定",
                      "我没改任何东西，你说的那个我看不到；你可以选。",
                      [{"text": "她承认不确定", "bot_behavior": "admit_uncertainty"},
                       {"text": "她提供选择", "bot_behavior": "offer_choices"}])
        state = self.maintenance()
        self.assertEqual(state["evidence"],
                         {"admit_uncertainty": 2, "offer_choices": 1,
                          "protect_privacy": 1})
        self.assertEqual(state["min_evidence"], 3)
        self.assertEqual(state["last_writes"], 0)
        self.assertEqual(state["last_persona"], "")
        self.assertFalse(state["dirty"])
        self.assertFalse(state["degraded"])
        self.assertEqual(state["failures"], 0)
        self.assertEqual(self.persona()["revision"], 0)
        # One more independent admit_uncertainty observation is enough; no gate moved.
        self.exchange("这个你怎么看？", "我确实不确定，先说清楚哪些我不知道。",
                      [{"text": "她承认不确定", "bot_behavior": "admit_uncertainty"}])
        state = self.maintenance()
        self.assertEqual(state["evidence"]["admit_uncertainty"], 3)
        self.assertEqual(state["min_evidence"], 3)
        self.assertGreaterEqual(self.persona()["revision"], 1)


if __name__ == "__main__":
    unittest.main()
