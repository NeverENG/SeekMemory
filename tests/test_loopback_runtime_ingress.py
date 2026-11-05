"""Real loopback runtime ingress preserves legacy Source evidence and subject isolation."""

from __future__ import annotations

import datetime
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from adapters.loopback.runtime import MemoryService


class LiveRuntimeIngressTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory(prefix="seekmemory-live-runtime-")
        self.addCleanup(self.root.cleanup)
        self.legacy = MemoryService(Path(self.root.name) / "legacy", {"owner_umo": "owner"}, quiet=True)
        self.live = MemoryService(Path(self.root.name) / "live", {"owner_umo": "owner"}, quiet=True)
        self.addCleanup(self.legacy.store.close)
        self.addCleanup(self.live.store.close)

    @staticmethod
    def _user() -> dict:
        at = "2026-11-05T00:00:00.000Z"
        return {
            "kind": "accept_user", "subject_key": "owner", "event_id": "u1",
            "input": {
                "session_id": "conv", "text": "hello?", "speaker_id": "owner",
                "event_time": datetime.datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp(),
                "received_at": 1.0, "event_id": "u1", "mentioned": True, "scene": "group",
            },
        }

    def _source(self, service: MemoryService, source_id: str) -> dict:
        return asdict(service.store.sources.sources_by_ids([source_id])[source_id])

    def test_user_and_assistant_evidence_matches_legacy_capture(self) -> None:
        user = self._user()
        legacy_status, old = self.legacy.capture({
            "subject_key": "owner", "session": "conv", "role": "user", "text": "hello?",
            "at": "2026-11-05T00:00:00.000Z", "msg_id": "u1",
        })
        self.assertEqual(legacy_status, 200)
        status, accepted = self.live.runtime_event(user)
        self.assertEqual(status, 200)
        self.assertEqual(accepted["source_id"], old["source_id"])
        self.assertEqual(accepted["turn_id"], "u1")
        self.assertEqual(accepted["decision"]["action"], "reply")
        self.assertEqual(self._source(self.live, old["source_id"]), self._source(self.legacy, old["source_id"]))
        self.assertEqual(len(self.live.buffer.items), 1)
        repeat_status, repeated = self.live.runtime_event(user)
        self.assertEqual(repeat_status, 200)
        self.assertEqual(repeated["source_id"], old["source_id"])
        self.assertEqual(len(self.live.buffer.items), 1)

        reply = {
            "subject_key": "owner", "session": "conv", "role": "assistant", "speaker": "assistant",
            "text": "hi", "at": "2026-11-05T00:00:05.000Z", "msg_id": "a1",
            "reply_to": old["source_id"],
        }
        old_status, old_reply = self.legacy.capture(reply)
        self.assertEqual(old_status, 200)
        status, result = self.live.runtime_event({
            "kind": "record_reply", "subject_key": "owner", "session_id": "conv",
            "text": "hi", "speaker_id": "assistant", "turn_id": "a1", "at": reply["at"],
            "reply_to": old["source_id"], "recall_ids": [],
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["assistant_source_id"], old_reply["source_id"])
        self.assertEqual(self._source(self.live, old_reply["source_id"]),
                         self._source(self.legacy, old_reply["source_id"]))
        self.assertEqual(len(self.live.buffer.items), 2)

    def test_subject_and_malformed_input_fail_without_writing(self) -> None:
        request = self._user()
        request["subject_key"] = "intruder"
        self.assertEqual(self.live.runtime_event(request), (403, {"error": "subject_mismatch"}))
        self.assertEqual(self.live.runtime_context({
            "subject_key": "intruder", "session_id": "conv", "query": "secret",
        }), (403, {"error": "subject_mismatch"}))
        request["subject_key"] = "owner"
        request["input"]["host_object"] = {}
        self.assertEqual(self.live.runtime_event(request)[0], 400)
        self.assertEqual(self.live.buffer.items, [])

    def test_invalid_runtime_facts_are_rejected_before_capture(self) -> None:
        # A malformed host event must not leave evidence behind if runtime observation fails.
        for field, value in (("event_time", "not-a-time"), ("unread_seq", "bad-cursor"),
                             ("text", 123), ("kind", "tool_call")):
            with self.subTest(field=field):
                request = self._user()
                request["input"][field] = value
                status, result = self.live.runtime_event(request)
                self.assertEqual((status, result), (400, {"error": "invalid_runtime_input"}))
                self.assertEqual(self.live.buffer.items, [])

    def test_failed_capture_remains_retryable_without_duplicate_evidence(self) -> None:
        request = self._user()
        with patch.object(self.live.runtime_ingress, "capture", return_value=(503, {"error": "unavailable"})):
            self.assertEqual(self.live.runtime_event(request), (503, {"error": "unavailable"}))
        self.assertEqual(self.live.buffer.items, [])
        status, accepted = self.live.runtime_event(request)
        self.assertEqual(status, 200)
        self.assertEqual(len(self.live.buffer.items), 1)
        self.assertTrue(accepted["source_id"])

    def test_runtime_context_uses_existing_disclosed_recall_result(self) -> None:
        with patch.object(self.live.recall_service, "preview", return_value={
            "block": "<relevant-memories>safe</relevant-memories>",
            "info": {"final_ids": ["a1"]},
        }):
            status, context = self.live.runtime_context({
                "subject_key": "owner", "session_id": "conv", "query": "hello",
                "speaker_id": "owner", "private": True, "reason": "inbound",
            })
        self.assertEqual(status, 200)
        self.assertEqual(context["text"], "<relevant-memories>safe</relevant-memories>")
        self.assertEqual(context["info"]["final_ids"], ["a1"])

    def test_explicit_dsh_budget_is_not_bypassed_by_runtime_context(self) -> None:
        with patch.object(self.live.recall_service, "preview", return_value={
            "block": "too long", "info": {"final_ids": ["a1"], "chars": 8},
        }):
            status, context = self.live.runtime_context({
                "subject_key": "owner", "session_id": "conv", "query": "hello",
                "speaker_id": "owner", "private": True, "budget_chars": 2, "k": 1,
            })
        self.assertEqual(status, 200)
        self.assertEqual(context["text"], "")
        self.assertEqual(context["info"]["final_ids"], [])

    def test_private_flag_is_boolean_before_disclosure_on_both_routes(self) -> None:
        for route, omitted_default in ((self.live.recall, True), (self.live.runtime_context, False)):
            for value in ("false", "true", 0, None, []):
                with self.subTest(route=route.__name__, value=value):
                    with patch.object(self.live.recall_service, "preview") as preview:
                        self.assertEqual(route({
                            "subject_key": "owner", "session_id": "conv",
                            "query": "fixture", "private": value,
                        }), (400, {"error": "invalid_private_flag"}))
                        preview.assert_not_called()
            with patch.object(self.live.recall_service, "preview", side_effect=lambda *_args, **_kw: {
                "block": "fixture", "info": {"final_ids": []},
            }) as preview:
                for private in (False, True):
                    self.assertEqual(route({"subject_key": "owner", "session_id": "conv",
                                            "query": "fixture", "private": private})[0], 200)
                    self.assertIs(preview.call_args.args[2], private)
                self.assertEqual(route({"subject_key": "owner", "session_id": "conv",
                                        "query": "fixture"})[0], 200)
                self.assertIs(preview.call_args.args[2], omitted_default)
                self.assertEqual(route({"subject_key": "intruder", "private": "false"})[0], 403)

if __name__ == "__main__":
    unittest.main()
