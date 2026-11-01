"""End-to-end persona growth through the real loopback service and storage.

The model is stubbed at the one place the host is allowed to supply it: the
`chat_response.text` of an extraction commit. Everything else (capture, queue,
extraction validation, persistence, maintenance, /persona) is production code.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.loopback.runtime import MemoryService  # noqa: E402
from services.management_service import ManagementService  # noqa: E402
from store import Store  # noqa: E402
from store.cache import Cache  # noqa: E402

UMO = "lab:persona-e2e"
SEED = ROOT / "persona_seeds" / "big_fish" / "persona.json"


def _item(user_sid: str, bot_sid: str, text: str, behavior: str,
          confidence: float) -> dict:
    return {
        "level": "scene", "text": text, "tags": "persona e2e",
        "about": "relation", "subject_kind": "self", "subject_id": "self",
        "event_at": "2026-11-01T10:00:00", "confidence": confidence,
        "arousal": 0.2, "valence": 0,
        "bot_behavior": behavior, "bot_action": text,
        "evidence_source_ids": [user_sid, bot_sid],
    }


class PersonaGrowthEndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        # Plain mkdir keeps the inherited ACL; TemporaryDirectory applies a
        # private mode that some Windows restricted tokens cannot reopen.
        self.dir = Path(tempfile.gettempdir()) / f"sm-persona-e2e-{uuid4().hex}"
        self.dir.mkdir()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = self.dir / "memory.db"
        seed = json.loads(SEED.read_text(encoding="utf-8"))
        store = Store(str(self.db))
        try:
            cache = Cache(store.artifacts)
            cache.load()
            ManagementService(store.artifacts, store.sources, store.ledger,
                              cache, None).bootstrap_persona(seed)
        finally:
            store.close()
        self.service = MemoryService(
            self.dir, {"owner_umo": UMO, "persona_min_interval_s": 0}, quiet=True)
        self.addCleanup(self.service.store.close)

    def persona(self) -> dict:
        code, body = self.service.persona({"subject_key": UMO})
        self.assertEqual(code, 200)
        return body

    def grow(self, number: int, behavior: str = "respond_emotion",
             confidence: float = 0.95) -> dict:
        """Capture one reply-paired exchange and commit one validated observation."""
        code, user = self.service.capture({
            "subject_key": UMO, "role": "user", "msg_id": f"u{number}",
            "text": f"第{number}次：我今天心情不好，想跟你说说。",
        })
        self.assertEqual(code, 200, user)
        code, bot = self.service.capture({
            "subject_key": UMO, "role": "assistant", "msg_id": f"a{number}",
            "reply_to": user["source_id"], "text": "我在，先陪你缓一缓。",
        })
        self.assertEqual(code, 200, bot)
        code, task = self.service.extract_plan({"subject_key": UMO})
        self.assertEqual(code, 200, task)
        self.assertEqual(len(task["source_ids"]), 2, "both sides must be in the batch")
        payload = _item(user["source_id"], bot["source_id"],
                        f"第{number}次：她先接住情绪。", behavior, confidence)
        code, result = self.service.extract_commit({
            "task_id": task["task_id"], "source_ids": task["source_ids"],
            "chat_response": {"text": json.dumps([payload], ensure_ascii=False)},
        })
        self.assertEqual(code, 200, result)
        self.assertEqual(result["written"], 1, result)
        return self.persona()

    def test_three_paired_observations_grow_persona_and_survive_restart(self) -> None:
        before = self.persona()
        self.assertEqual(before["revision"], 1)
        self.assertEqual(self.grow(1)["revision"], 1)
        self.assertEqual(self.grow(2)["revision"], 1)
        after = self.grow(3)
        self.assertEqual(after["revision"], 2)
        self.assertNotEqual(after["text"], before["text"])
        self.assertIn("回应情绪", after["text"])
        self.assertFalse(self.service.persona_evolution.degraded)

        # Reopening the service is the cold-start path of a restarted kernel.
        self.service.store.close()
        reopened = MemoryService(
            self.dir, {"owner_umo": UMO, "persona_min_interval_s": 0}, quiet=True)
        try:
            persisted = reopened.persona({"subject_key": UMO})[1]
            self.assertEqual(persisted["text"], after["text"])
            self.assertEqual(persisted["revision"], after["revision"])
        finally:
            reopened.store.close()
        self.service = reopened  # addCleanup closes it again harmlessly

    def test_two_observations_or_low_confidence_leave_persona_unchanged(self) -> None:
        before = self.persona()
        self.grow(1)
        self.grow(2)
        self.assertEqual(self.persona(), before)
        low = self.grow(3, confidence=0.80)
        self.assertEqual(low, before)
        impressions = [a for a in self.service.cache.active("memory")
                       if a.payload.get("level") == "impression"]
        self.assertEqual(impressions, [])

    def test_distinct_behaviors_do_not_share_an_impression(self) -> None:
        before = self.persona()
        self.grow(1, behavior="respond_emotion")
        self.grow(2, behavior="clarify_question")
        self.grow(3, behavior="admit_uncertainty")
        self.assertEqual(self.persona(), before)

    def test_restart_reconciles_evidence_left_by_an_interrupted_process(self) -> None:
        # Simulate a crash between a successful extraction and maintenance.
        self.service.persona_evolution.after_extraction = lambda: None
        self.grow(1)
        self.grow(2)
        self.grow(3)
        self.assertEqual(self.persona()["revision"], 1)
        self.service.store.close()
        reopened = MemoryService(
            self.dir, {"owner_umo": UMO, "persona_min_interval_s": 0}, quiet=True)
        try:
            code, _ = reopened.extract_plan({"subject_key": UMO})
            self.assertEqual(code, 204)  # no pending extraction left
            self.assertEqual(reopened.persona({"subject_key": UMO})[1]["revision"], 2)
        finally:
            reopened.store.close()

    def test_repeated_maintenance_is_a_noop(self) -> None:
        self.grow(1)
        self.grow(2)
        self.grow(3)
        grown = self.persona()
        history = self.service.store.artifacts.history(
            self.service.status_service.persona()["id"])
        self.assertEqual(self.service.persona_evolution.maybe_run(), False)
        from maintain.persona import distill_self_persona
        from maintain.self_impression import build_self_impressions

        build_self_impressions(self.service.store.artifacts,
                               self.service.store.sources, self.service.cache)
        again = distill_self_persona(self.service.store.artifacts,
                                     self.service.store.sources, self.service.cache)
        self.assertEqual(len(self.service.store.artifacts.history(again.header.id)),
                         len(history))
        self.assertEqual(self.persona(), grown)

    def test_mixed_behaviors_wait_for_three_of_one_kind(self) -> None:
        """Four valid episodes across kinds do not prove any one stable trait."""
        self.grow(1, behavior="protect_privacy")
        self.grow(2, behavior="admit_uncertainty")
        self.grow(3, behavior="admit_uncertainty")
        fourth = self.grow(4, behavior="offer_choices")
        self.assertEqual(fourth["revision"], 1)
        diagnostics = self.service.status()[1]["persona_maintenance"]
        self.assertEqual(diagnostics["evidence"], {
            "protect_privacy": 1, "admit_uncertainty": 2, "offer_choices": 1,
        })
        self.assertEqual(diagnostics["needed_by_behavior"], {
            "protect_privacy": 2, "admit_uncertainty": 1, "offer_choices": 2,
        })
        self.assertEqual(diagnostics["last_writes"], 0)
        fifth = self.grow(5, behavior="admit_uncertainty")
        self.assertEqual(fifth["revision"], 2)

    def test_new_commits_drain_dirty_even_inside_success_interval(self) -> None:
        """A successful no-op cannot defer a newly completed third episode."""
        self.service.persona_evolution.min_interval_s = 3600
        self.assertEqual(self.grow(1)["revision"], 1)
        self.assertEqual(self.grow(2)["revision"], 1)
        self.assertEqual(self.grow(3)["revision"], 2)


if __name__ == "__main__":
    unittest.main()
