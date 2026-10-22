"""Round-robin topic batch selection tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import DialogueTurn  # noqa: E402
from app.flush_policy import select_topic_batches  # noqa: E402


def turn(session: str, topic: str, text: str = "hello") -> DialogueTurn:
    return DialogueTurn(session, "u", "user", text, "", "", topic)


class RoundRobinTest(unittest.TestCase):
    def test_single_long_session_cannot_take_every_slot(self) -> None:
        items = [turn("a", "t1"), turn("a", "t1"), turn("a", "t2"), turn("b", "t3")]
        batches = select_topic_batches(items, 2)
        self.assertEqual([(session, topic) for session, topic, _ in batches],
                         [("a", "t1"), ("b", "t3")])

    def test_sessions_rotate_until_cap(self) -> None:
        items = [turn("a", "t1"), turn("b", "t2"), turn("c", "t3"), turn("a", "t4")]
        self.assertEqual(
            [(session, topic) for session, topic, _ in select_topic_batches(items, 4)],
            [("a", "t1"), ("b", "t2"), ("c", "t3"), ("a", "t4")],
        )

    def test_cap_limits_batches(self) -> None:
        items = [turn("a", "t1"), turn("b", "t2"), turn("c", "t3")]
        self.assertEqual(len(select_topic_batches(items, 2)), 2)
        self.assertEqual(len(select_topic_batches(items, 99)), 3)

    def test_empty_input_returns_no_batches(self) -> None:
        self.assertEqual(select_topic_batches([], 3), [])


if __name__ == "__main__":
    unittest.main()
