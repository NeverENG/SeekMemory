"""Bounded Trace ring tests: separation, bounds and trimming."""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from webui.trace import Trace, TraceRow  # noqa: E402


class TraceTest(unittest.TestCase):
    def test_ring_keeps_newest_rows(self) -> None:
        trace = Trace(maxlen=5)
        for index in range(8):
            trace.record("capacity", "normal", {"index": index})
        self.assertEqual(trace.count, 5)
        self.assertEqual([row.context["index"] for row in trace.rows],
                         [3, 4, 5, 6, 7])

    def test_trim_keeps_target_and_reports_removed(self) -> None:
        trace = Trace(maxlen=20)
        for index in range(10):
            trace.record("scheduler", "running", {"index": index})
        self.assertEqual(trace.trim(3), 7)
        self.assertEqual([row.context["index"] for row in trace.rows], [7, 8, 9])

    def test_context_keeps_scalars_only(self) -> None:
        trace = Trace()
        trace.record(
            "capacity", "pressured", {"rows": 3, "text": "hello", "bad": {"a": 1}}
        )
        self.assertEqual(trace.rows[-1].context, {"rows": 3, "text": "hello"})

    def test_oldest_age_uses_first_row(self) -> None:
        trace = Trace()
        trace.record("capacity", "normal", {})
        trace.rows[0] = TraceRow(
            at=(datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat(),
            kind="capacity",
            status="normal",
        )
        self.assertGreaterEqual(trace.oldest_age_seconds(), 89)

    def test_trace_is_independent_from_a_journal_file(self) -> None:
        trace = Trace()
        self.assertFalse(hasattr(trace, "path"))
        trace.trim(0)
        self.assertEqual(trace.count, 0)


if __name__ == "__main__":
    unittest.main()
