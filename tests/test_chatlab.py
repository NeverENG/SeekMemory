"""ChatLab v0.0.2 parser and stable imported Source identity contracts."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.history_import_limits import JSONL_MAX_LINE_BYTES
from adapters.chatlab import (
    ChatLabFormatError,
    inspect_chatlab,
    iter_chatlab_messages,
    iter_chatlab_messages_sorted,
)
from core.source import make_import_source_id, make_source_id


def _message(message_id: str, sender: str = "user-1", timestamp: int = 1_700_000_000,
             content: str = "hello", **extra: object) -> dict:
    return {
        "_type": "message",
        "platformMessageId": message_id,
        "sender": sender,
        "timestamp": timestamp,
        "type": 0,
        "content": content,
        **extra,
    }


class ChatLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_json_preview_and_messages_preserve_platform_identity_and_reply(self) -> None:
        path = self.root / "conversation.json"
        path.write_text(
            json.dumps(
                {
                    "chatlab": {"version": "0.0.2", "exportedAt": 1},
                    "meta": {"name": "private", "platform": "qq", "type": "private"},
                    "members": [
                        {"platformId": "bot-1", "accountName": "bot"},
                        {"platformId": "user-1", "accountName": "user"},
                    ],
                    "messages": [
                        _message("m-2", sender="bot-1", timestamp=1_700_000_060,
                                 content="answer", replyToMessageId="m-1"),
                        _message("m-1", timestamp=1_700_000_000),
                    ],
                }
            ),
            encoding="utf-8",
        )

        preview = inspect_chatlab(path)
        messages = list(iter_chatlab_messages(path))
        self.assertEqual(preview.format, "json")
        self.assertEqual(preview.version, "0.0.2")
        self.assertEqual(preview.sender_counts, {"bot-1": 1, "user-1": 1})
        self.assertEqual(preview.accepted_messages, 2)
        self.assertEqual([row.external_message_id for row in messages], ["m-2", "m-1"])
        self.assertEqual(messages[0].reply_to_message_id, "m-1")
        self.assertEqual(messages[0].at, "2023-11-14T22:14:20+00:00")
        self.assertEqual(
            [row.external_message_id for row in iter_chatlab_messages_sorted(path)],
            ["m-1", "m-2"],
        )

    def test_jsonl_sort_is_stable_and_uses_bounded_external_runs(self) -> None:
        path = self.root / "conversation.jsonl"
        rows = [
            {"_type": "header", "chatlab": {"version": "0.0.2"},
             "meta": {"name": "private", "platform": "qq", "type": "private"}},
            _message("later", timestamp=20),
            _message("first-a", timestamp=10),
            _message("first-b", timestamp=10),
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        from unittest.mock import patch

        with patch("adapters.chatlab.SORT_RUN_RECORDS", 1):
            messages = list(iter_chatlab_messages_sorted(path))
        self.assertEqual(
            [row.external_message_id for row in messages],
            ["first-a", "first-b", "later"],
        )

    def test_jsonl_skips_invalid_rows_but_reports_missing_ids(self) -> None:
        path = self.root / "conversation.jsonl"
        rows = [
            {"_type": "header", "chatlab": {"version": "0.0.2"},
             "meta": {"name": "private", "platform": "qq", "type": "private"}},
            {"_type": "member", "platformId": "bot-1", "accountName": "bot"},
            _message("m-1"),
            '{"_type":"message",',
            _message("", content="no stable id"),
            _message("m-2", content=None),
        ]
        path.write_text("\n".join(
            row if isinstance(row, str) else json.dumps(row) for row in rows
        ), encoding="utf-8")

        preview = inspect_chatlab(path)
        self.assertEqual(preview.accepted_messages, 1)
        self.assertEqual(preview.skipped_rows, 2)
        self.assertEqual(preview.missing_id_rows, 1)
        self.assertEqual(preview.sender_counts["user-1"], 2)
        self.assertEqual(preview.warnings[0]["reason"], "invalid_json")
        with self.assertRaisesRegex(ValueError, "platformMessageId"):
            list(iter_chatlab_messages(path))

    def test_jsonl_rejects_a_record_over_the_line_byte_limit(self) -> None:
        path = self.root / "oversized.jsonl"
        header = {
            "_type": "header",
            "chatlab": {"version": "0.0.2"},
            "meta": {"name": "private", "platform": "qq", "type": "private"},
        }
        with path.open("wb") as stream:
            stream.write(json.dumps(header).encode("utf-8") + b"\n")
            stream.write(b"{" + b" " * JSONL_MAX_LINE_BYTES)

        with self.assertRaisesRegex(ChatLabFormatError, "字节上限"):
            inspect_chatlab(path)

    def test_preview_rejects_more_than_two_private_chat_speakers(self) -> None:
        path = self.root / "three-speakers.jsonl"
        rows = [
            {"_type": "header", "chatlab": {"version": "0.0.2"},
             "meta": {"name": "private", "platform": "qq", "type": "private"}},
            _message("one", sender="user-1"),
            _message("two", sender="bot-1"),
            _message("three", sender="extra-1"),
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

        with self.assertRaisesRegex(ChatLabFormatError, "超过两位发言者"):
            inspect_chatlab(path)

    def test_preview_bounds_declared_private_member_metadata(self) -> None:
        path = self.root / "three-members.json"
        path.write_text(json.dumps({
            "chatlab": {"version": "0.0.2"},
            "meta": {"name": "private", "platform": "qq", "type": "private"},
            "members": [
                {"platformId": "user-1"},
                {"platformId": "bot-1"},
                {"platformId": "extra-1"},
            ],
            "messages": [_message("one", sender="user-1")],
        }), encoding="utf-8")

        with self.assertRaisesRegex(ChatLabFormatError, "最多包含两名成员"):
            inspect_chatlab(path)

    def test_rejects_group_unsupported_version_and_late_member(self) -> None:
        for kind, version in (("group", "0.0.2"), ("private", "0.0.1")):
            path = self.root / f"{kind}-{version}.json"
            path.write_text(json.dumps({
                "chatlab": {"version": version},
                "meta": {"name": "conversation", "platform": "qq", "type": kind},
                "messages": [_message("m-1")],
            }), encoding="utf-8")
            with self.subTest(kind=kind, version=version):
                with self.assertRaises(ChatLabFormatError):
                    inspect_chatlab(path)

        path = self.root / "late-member.jsonl"
        rows = [
            {"_type": "header", "chatlab": {"version": "0.0.2"},
             "meta": {"name": "private", "platform": "qq", "type": "private"}},
            _message("m-1"),
            {"_type": "member", "platformId": "bot-1", "accountName": "bot"},
        ]
        path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
        with self.assertRaisesRegex(ChatLabFormatError, "member 行"):
            inspect_chatlab(path)

    def test_import_id_is_stable_unambiguous_and_does_not_change_live_id(self) -> None:
        first = make_import_source_id(
            format_id="chatlab", conversation_id="qq:friend:a|b", external_message_id="c"
        )
        same = make_import_source_id(
            format_id="chatlab", conversation_id="qq:friend:a|b", external_message_id="c"
        )
        other = make_import_source_id(
            format_id="chatlab", conversation_id="qq:friend:a", external_message_id="b|c"
        )
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 67)
        self.assertEqual(
            make_source_id(session_id="s", speaker_id="u", role="user", text="t"),
            "s_5cea56389423b21d2101fedb",
        )
        with self.assertRaises(ValueError):
            make_import_source_id(format_id="chatlab", conversation_id="", external_message_id="1")


if __name__ == "__main__":
    unittest.main()
