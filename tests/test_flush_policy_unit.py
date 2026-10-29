"""Pure flush scheduling decisions.

纯刷新调度决策。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.flush_policy import decide_flush

class FlushPolicyTest(unittest.TestCase):
    def test_backlog_overrides_worth_now(self):
        got = decide_flush(pending=30, idle_seconds=31, worth_now=False,
                           flushes_today=0, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertTrue(got.should)
        self.assertEqual(got.reason, "backlog")

    def test_backlog_waits_for_quiet_window(self):
        got = decide_flush(pending=30, idle_seconds=10, worth_now=False,
                           flushes_today=0, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertFalse(got.should)

    def test_expired_topic_overrides_daily_cap(self):
        got = decide_flush(pending=2, idle_seconds=10, worth_now=False,
                           flushes_today=2, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30, topic_age_seconds=86400,
                           topic_ttl_seconds=86400)
        self.assertTrue(got.should)
        self.assertEqual(got.reason, "topic_expired")

    def test_daily_cap_blocks(self):
        got = decide_flush(pending=100, idle_seconds=999, worth_now=True,
                           flushes_today=2, idle_flush_seconds=180,
                           min_pending=8, max_flushes_per_day=2,
                           backlog_flush_at=30)
        self.assertFalse(got.should)
        self.assertEqual(got.reason, "daily_cap")


if __name__ == "__main__":
    unittest.main()
