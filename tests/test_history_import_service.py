"""End-to-end import orchestration over local Source and extraction stores."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import WriteOutcome
from adapters.chatlab import ChatLabReader
from services.import_policy import RoleSelection
from services.import_service import ImportService
from store import open_store
from webui.import_files import ImportFileError, ImportFileStore
from webui.journal import Journal


class Upload:
    filename = "history.json"
    size = None

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
                    "messages": [
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
                    ],
                }
            ),
            encoding="utf-8",
        )


class FakeIngest:
    def __init__(self) -> None:
        self.calls: list[dict] = []

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

    async def test_invalid_row_from_third_speaker_rejects_file_before_source_admission(self):
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
        preview = await self.service.inspect_upload(staged.key)
        self.assertEqual(preview["senderCounts"]["third-party"], 1)
        with self.assertRaisesRegex(ValueError, "两位发言者"):
            await self.service.validate_stage(staged.key, self.selection)
        self.assertEqual(
            self.db.conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
