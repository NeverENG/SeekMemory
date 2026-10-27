"""End-to-end import orchestration over local Source and extraction stores."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import WriteOutcome
from adapters.chatlab import ChatLabReader
from services.import_policy import RoleSelection, build_source_entries, reply_source_ids
from services.import_service import ImportService
from services.import_utils import VALIDATION_BATCH, take
from store import open_store
from webui.import_files import ImportFileError, ImportFileStore
from webui.journal import Journal


class Upload:
    size = None

    def __init__(self, messages: list[dict] | None = None) -> None:
        self.filename = "history.json"
        self.messages = messages or [
            {
                "platformMessageId": "user-message",
                "sender": "user-1",
                "timestamp": 1_700_000_000,
                "content": "hello",
            },
            {
                "platformMessageId": "bot-message",
                "sender": "bot-1",
                "timestamp": 1_700_000_001,
                "content": "hello there",
                "replyToMessageId": "user-message",
            },
        ]

    async def save(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "chatlab": {"version": "0.0.2"},
                    "meta": {"name": "private", "platform": "qq", "type": "private"},
                    "members": [
                        {"platformId": "bot-1", "accountName": "Bot"},
                        {"platformId": "user-1", "accountName": "User"},
                    ],
                    "messages": self.messages,
                }
            ),
            encoding="utf-8",
        )


class LargeReplyJsonlUpload:
    filename = "history.jsonl"
    size = None
    pairs = 25_001

    async def save(self, path: Path) -> None:
        with path.open("w", encoding="utf-8") as stream:
            rows = [
                {
                    "_type": "header",
                    "chatlab": {"version": "0.0.2"},
                    "meta": {"name": "private", "platform": "qq", "type": "private"},
                },
                {"_type": "member", "platformId": "bot-1", "accountName": "Bot"},
                {"_type": "member", "platformId": "user-1", "accountName": "User"},
            ]
            for row in rows:
                stream.write(json.dumps(row) + "\n")
            for index in range(self.pairs):
                user_id = f"user-{index}"
                timestamp = 1_700_000_000 + index * 2
                for row in (
                    {
                        "_type": "message",
                        "platformMessageId": user_id,
                        "sender": "user-1",
                        "timestamp": timestamp,
                        "content": "same topic question",
                    },
                    {
                        "_type": "message",
                        "platformMessageId": f"bot-{index}",
                        "sender": "bot-1",
                        "timestamp": timestamp + 1,
                        "content": "same topic answer",
                        "replyToMessageId": user_id,
                    },
                ):
                    stream.write(json.dumps(row) + "\n")


class FakeIngest:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_first_calls = 0

    async def extract(self, turns, model, *, owner_id, strict, require_evidence):
        self.calls.append(
            {
                "turns": turns,
                "model": model,
                "owner_id": owner_id,
                "strict": strict,
                "require_evidence": require_evidence,
            }
        )
        if len(self.calls) <= self.fail_first_calls:
            raise RuntimeError("retryable model failure")
        return WriteOutcome(written=1)


class FakeMaintenance:
    def __init__(self) -> None:
        self.calls = 0

    async def import_persona_update(self) -> dict:
        self.calls += 1
        return {"status": "unchanged"}


class HistoryImportServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.files = ImportFileStore(Path(self.temp.name) / "staging")
        self.ingest = FakeIngest()
        self.maintenance = FakeMaintenance()
        self.journal = Journal(Path(self.temp.name) / "journal.jsonl")
        self.provider_sessions: list[str | None] = []

        async def provider_for(session: str | None):
            self.provider_sessions.append(session)
            return object()

        self.service = ImportService(
            imports=self.db.imports,
            extraction=self.db.extraction,
            ingest=self.ingest,
            maintenance=self.maintenance,
            files=self.files,
            reader=ChatLabReader(),
            provider_for=provider_for,
            journal=self.journal,
            logger=logging.getLogger("test.history_import"),
        )
        self.selection = RoleSelection(
            bot_platform_id="bot-1",
            target_platform_id="user-1",
            target_umo="qq:FriendMessage:user-1",
            bot_member_id="bot-1",
            target_member_id="user-1",
        )

    async def test_import_admits_sources_extracts_without_triage_and_updates_persona(self):
        staged = await self.files.save_upload(Upload())
        upload_preview = await self.service.inspect_upload(staged.key)
        self.assertEqual(upload_preview["messageCount"], 2)
        preview = await self.service.validate_stage(staged.key, self.selection)
        self.assertEqual(preview["uniqueSourceCount"], 2)
        self.assertEqual(preview["roleMapping"]["assistantMemberId"], "bot-1")

        task_id = self.service.create_task(staged.key, self.selection)
        await self.service.run(task_id, self.selection)

        task = self.service.task(task_id)
        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["source_count"], 2)
        self.assertEqual(task["extracted_count"], 2)
        self.assertEqual(task["pending_count"], 0)
        self.assertEqual(self.maintenance.calls, 1)
        self.assertEqual(self.provider_sessions, ["qq:FriendMessage:user-1"])
        self.assertTrue(self.ingest.calls)
        self.assertTrue(
            all(call["owner_id"] == "user-1" for call in self.ingest.calls)
        )
        self.assertTrue(all(call["strict"] for call in self.ingest.calls))
        self.assertTrue(all(call["require_evidence"] for call in self.ingest.calls))
        imported_turns = [turn for call in self.ingest.calls for turn in call["turns"]]
        self.assertEqual({turn.role for turn in imported_turns}, {"user", "assistant"})
        self.assertEqual({turn.session_id for turn in imported_turns}, {"qq:FriendMessage:user-1"})
        assistant = next(turn for turn in imported_turns if turn.role == "assistant")
        self.assertTrue(assistant.reply_to)
        source_rows = self.db.conn.execute("SELECT id FROM sources ORDER BY at").fetchall()
        persisted = self.db.sources.sources_by_ids([str(row["id"]) for row in source_rows])
        self.assertEqual({source.session_id for source in persisted.values()}, {"qq:FriendMessage:user-1"})
        self.assertEqual({source.role for source in persisted.values()}, {"user", "assistant"})
        self.assertNotIn("hello there", json.dumps(list(self.journal.events)))
        with self.assertRaises(ImportFileError):
            self.files.path_for_key(staged.key)

    async def test_many_chunks_do_not_rescan_all_task_counts_each_time(self):
        messages = [
            {
                "platformMessageId": f"message-{index}",
                "sender": "bot-1" if index == 0 else "user-1",
                "timestamp": 1_700_000_000 + index,
                "content": "same topic history message",
            }
            for index in range(250)
        ]
        staged = await self.files.save_upload(Upload(messages))
        await self.service.inspect_upload(staged.key)
        await self.service.validate_stage(staged.key, self.selection)
        task_id = self.service.create_task(staged.key, self.selection)

        count_calls = 0
        original_counts = self.db.imports.counts

        def counted(task: str):
            nonlocal count_calls
            count_calls += 1
            return original_counts(task)

        self.db.imports.counts = counted
        await self.service.run(task_id, self.selection)

        self.assertEqual(len(self.ingest.calls), 3)
        # The task summary is read once while running and once when it is finalized.
        self.assertEqual(count_calls, 3)

    async def test_retry_wait_resumes_from_the_indexed_retry_queue(self):
        from unittest.mock import patch

        staged = await self.files.save_upload(Upload())
        await self.service.inspect_upload(staged.key)
        await self.service.validate_stage(staged.key, self.selection)
        task_id = self.service.create_task(staged.key, self.selection)
        self.ingest.fail_first_calls = 1
        clock = [datetime(2026, 10, 1, 0, 0, 0)]

        def now_iso():
            return clock[0].isoformat(timespec="seconds")

        async def advance_sleep(seconds: float) -> None:
            clock[0] += timedelta(seconds=seconds)

        with (
            patch("services.import_runner._now_iso", side_effect=now_iso),
            patch("store.extraction.now_iso", side_effect=now_iso),
            patch("services.import_runner.asyncio.sleep", new=advance_sleep),
        ):
            await self.service.run(task_id, self.selection)

        self.assertEqual(len(self.ingest.calls), 2)
        self.assertEqual(self.service.task(task_id)["status"], "completed")

    async def test_reply_to_future_user_keeps_parent_topic_across_batches(self):
        first_at = 1_700_000_000
        messages = [
            {
                "platformMessageId": "early-bot-reply",
                "sender": "bot-1",
                "timestamp": first_at,
                "content": "answer",
                "replyToMessageId": "later-user-message",
            }
        ]
        messages.extend(
            {
                "platformMessageId": f"user-{index}",
                "sender": "user-1",
                "timestamp": first_at + index,
                "content": "same topic message",
            }
            for index in range(1, 500)
        )
        messages.append(
            {
                "platformMessageId": "later-user-message",
                "sender": "user-1",
                "timestamp": first_at + 6_000,
                "content": "a new topic after the time gap",
            }
        )
        staged = await self.files.save_upload(Upload(messages))
        await self.service.inspect_upload(staged.key)
        preview = await self.service.validate_stage(staged.key, self.selection)
        self.assertEqual(preview["uniqueSourceCount"], 501)
        task_id = self.service.create_task(staged.key, self.selection)
        await self.service.run(task_id, self.selection)

        imported_turns = [turn for call in self.ingest.calls for turn in call["turns"]]
        bot_reply = next(turn for turn in imported_turns if turn.role == "assistant")
        parent = next(
            turn
            for turn in imported_turns
            if turn.role == "user" and turn.text == "a new topic after the time gap"
        )
        self.assertEqual(self.service.task(task_id)["status"], "completed")
        self.assertEqual(bot_reply.topic_id, parent.topic_id)

    async def test_large_jsonl_reply_references_are_processed_in_bounded_batches(self):
        staged = await self.files.save_upload(LargeReplyJsonlUpload())
        path = self.files.preview_path(staged.key)
        reader = self.service.validator.reader
        inspection = await asyncio.to_thread(reader.inspect, path)
        messages = reader.iter_messages_sorted(str(path))
        previous = None
        processed = 0
        max_batch = 0
        max_reply_ids = 0

        while True:
            message_batch = await asyncio.to_thread(take, messages, VALIDATION_BATCH)
            if not message_batch:
                break
            reply_ids = reply_source_ids(
                message_batch, self.selection.target_umo
            )
            entries, previous = await asyncio.to_thread(
                build_source_entries,
                message_batch,
                roles={"bot-1": "assistant", "user-1": "user"},
                target_umo=self.selection.target_umo,
                platform=inspection.platform,
                previous=previous,
                parent_topics={},
            )
            processed += len(entries)
            max_batch = max(max_batch, len(entries))
            max_reply_ids = max(max_reply_ids, len(reply_ids))

        self.assertEqual(processed, 50_002)
        self.assertLessEqual(max_batch, VALIDATION_BATCH)
        self.assertLessEqual(max_reply_ids, VALIDATION_BATCH)

    async def test_target_umo_must_match_the_confirmed_user_id(self):
        staged = await self.files.save_upload(Upload())
        await self.service.inspect_upload(staged.key)
        wrong_target = RoleSelection(
            bot_platform_id="bot-1",
            target_platform_id="user-1",
            target_umo="qq:FriendMessage:another-user",
            bot_member_id="bot-1",
            target_member_id="user-1",
        )
        with self.assertRaisesRegex(ValueError, "UMO"):
            await self.service.validate_stage(staged.key, wrong_target)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0
        )

    async def test_safely_skipped_rows_make_terminal_task_partial(self):
        staged = await self.files.save_upload(Upload())
        path = self.files.preview_path(staged.key)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["messages"].append(
            {
                "platformMessageId": "invalid-content-message",
                "sender": "user-1",
                "timestamp": 1_700_000_002,
                "content": "",
            }
        )
        path.write_text(json.dumps(document), encoding="utf-8")

        preview = await self.service.inspect_upload(staged.key)
        self.assertEqual(preview["skippedCount"], 1)
        await self.service.validate_stage(staged.key, self.selection)
        task_id = self.service.create_task(staged.key, self.selection)
        await self.service.run(task_id, self.selection)

        task = self.service.task(task_id)
        self.assertEqual(task["status"], "partial")
        self.assertEqual(task["source_count"], 2)
        self.assertEqual(task["extracted_count"], 2)
        self.assertEqual(task["skipped_count"], 1)

    async def test_reimport_preview_counts_existing_sources_as_skips(self):
        first = await self.files.save_upload(Upload())
        await self.service.inspect_upload(first.key)
        await self.service.validate_stage(first.key, self.selection)
        task_id = self.service.create_task(first.key, self.selection)
        await self.service.run(task_id, self.selection)

        second = await self.files.save_upload(Upload())
        await self.service.inspect_upload(second.key)
        preview = await self.service.validate_stage(second.key, self.selection)
        self.assertEqual(preview["uniqueSourceCount"], 0)
        self.assertEqual(preview["duplicateCount"], 2)

    async def test_third_speaker_is_rejected_during_preview_before_source_admission(self):
        staged = await self.files.save_upload(Upload())
        path = self.files.preview_path(staged.key)
        document = json.loads(path.read_text(encoding="utf-8"))
        document["messages"].append(
            {
                "platformMessageId": "third-party-message",
                "sender": "third-party",
                "timestamp": 1_700_000_002,
                "content": "",
            }
        )
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "超过两位发言者"):
            await self.service.inspect_upload(staged.key)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
