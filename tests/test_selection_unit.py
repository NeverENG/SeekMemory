"""Pure candidate selection scenarios.

纯候选筛选场景。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import make
from core.retrieval import RetrievalCandidate
from core.disclosure import DisclosureLevel, RecallScene, decide, safe_text
from recall.score import select
from kernel_support import _memory

class RetrievalCandidateTest(unittest.TestCase):
    def test_lexical_signal_participates_in_selection(self):
        plain = _memory(text="ordinary")
        lexical = _memory(text="bm25")
        got = select([RetrievalCandidate(plain), RetrievalCandidate(lexical, lexical=1.0)],
                     "unrelated query", 0.0, k=1, explore=0.0, gate=False)
        self.assertEqual([a.header.id for a in got], [lexical.header.id])

    def test_shared_cross_session_never_returns_raw_text(self):
        art = _memory(subject="u1", scope="shared", text="top secret phrase")
        art = make("memory", {**art.payload, "tags": "project"}, subject_id="u1",
                   scope="shared")
        scene = RecallScene("s2", "u1", "u1", ("u1",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.PARAPHRASE)
        self.assertNotIn("top secret phrase", safe_text(art, got.level))


if __name__ == "__main__":
    unittest.main()
