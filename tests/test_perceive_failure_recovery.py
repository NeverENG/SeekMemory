"""Check pending-view publication and legacy-file replacement failures.

检查待处理视图发布及旧文件替换失败。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import DialogueTurn
from core.source import Source
from perceive.buffer import Buffer
from store import open_store


class PendingFileRecoveryTest(unittest.TestCase):
    def test_failed_file_replace_keeps_old_file_and_live_view_for_each_operation(self):
        with tempfile.TemporaryDirectory() as temporary:
            for operation in ("add", "take", "take_topics", "restore", "confirm"):
                with self.subTest(operation=operation):
                    path = Path(temporary) / (operation + ".json")
                    buffer = Buffer(str(path))
                    turn = buffer.add("session", "原始待处理输入")
                    before = path.read_bytes()
                    items = list(buffer.items)
                    stamp = buffer.last_ts
                    actions = {
                        "add": lambda: buffer.add("session", "新增输入"),
                        "take": buffer.take,
                        "take_topics": lambda: buffer.take_topics({turn.topic_id}),
                        "restore": lambda: buffer.restore([DialogueTurn("session", "u", "user", "恢复输入")]),
                        "confirm": lambda: buffer.mark_succeeded([turn]),
                    }
                    with patch("perceive.pending_file.os.replace", side_effect=OSError("replace failed")):
                        with self.assertRaises(OSError):
                            actions[operation]()
                    self.assertEqual(buffer.items, items)
                    self.assertEqual(buffer.last_ts, stamp)
                    self.assertEqual(path.read_bytes(), before)
                    self.assertTrue(buffer.save_error)
                    self.assertEqual(list(Path(temporary).glob(".pending-*")), [])
                    self.assertTrue(buffer.save())
                    self.assertEqual(Buffer(str(path)).items, items)

    def test_confirm_source_less_row_keeps_new_equal_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            buffer = Buffer(str(Path(temporary) / "pending.json"))
            old = buffer.add("session", "相同文字")
            newer = buffer.add("session", "相同文字")
            buffer.mark_succeeded([old])
            self.assertEqual(len(buffer.items), 1)
            self.assertIs(buffer.items[0], newer)
            self.assertEqual(Buffer(buffer.path).items, [newer])


class ProjectionRecoveryTest(unittest.TestCase):
    def test_failed_projection_read_or_conversion_preserves_current_view(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        buffer = Buffer(extraction=db.extraction)
        buffer.add("s", "已有输入", sender="u", source_id="s1")
        rows, stamp = list(buffer.items), buffer.last_ts
        with patch.object(db.extraction, "pending_extractions", side_effect=OSError("read failed")):
            with self.assertRaises(OSError):
                buffer.reload()
        self.assertEqual(buffer.items, rows)
        self.assertEqual(buffer.last_ts, stamp)
        valid = db.extraction.pending_extractions()
        with patch.object(db.extraction, "pending_extractions", return_value=[*valid, {}]):
            with self.assertRaises(KeyError):
                buffer.reload()
        self.assertEqual(buffer.items, rows)
        self.assertEqual(buffer.last_ts, stamp)
        self.assertEqual(buffer.reload(), 1)

    def test_failed_queue_confirmation_keeps_projection_and_new_input(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        buffer = Buffer(extraction=db.extraction)
        old = buffer.add("s", "旧输入", sender="u", source_id="s1")
        with patch.object(db.extraction, "mark_extraction_succeeded", side_effect=OSError("queue failed")):
            with self.assertRaises(OSError):
                buffer.mark_succeeded([old])
        newer = buffer.add("s", "新输入", sender="u", source_id="s2")
        self.assertEqual(buffer.mark_succeeded([old]), 1)
        self.assertEqual(buffer.items, [newer])
        self.assertEqual(db.extraction.queue_counts()["extracted"], 1)
        self.assertEqual(db.sources.sources_by_ids(["s1"])["s1"].text, "旧输入")


if __name__ == "__main__":
    unittest.main()
