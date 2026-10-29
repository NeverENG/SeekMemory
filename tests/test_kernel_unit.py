"""Pure Source, version and disclosure scenarios.

纯 Source、版本及披露场景。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import revise
from core.source import Source, make_source_id
from core.versioning import VersionError, assert_next_revision
from core.disclosure import DisclosureLevel, RecallScene, decide, safe_text
from kernel_support import _memory

class SourceTest(unittest.TestCase):
    def test_id_is_stable_and_validate(self):
        sid = make_source_id(session_id="s", speaker_id="u1", role="user", text="hi", at="t")
        self.assertEqual(sid, make_source_id(session_id="s", speaker_id="u1", role="user", text="hi", at="t"))
        src = Source(sid, "turn", "s", "u1", "user", "hi", "t")
        src.validate()
        self.assertEqual(len(src.content_hash), 64)


class VersionTest(unittest.TestCase):
    def test_next_revision(self):
        first = _memory()
        second = revise(first, payload={"text": "new", "level": "fact"})
        assert_next_revision(None, first)
        assert_next_revision(first, second)
        with self.assertRaises(VersionError):
            assert_next_revision(first, first)


class DisclosureTest(unittest.TestCase):
    def test_same_session_private_is_full(self):
        art = _memory(subject="owner", scope="private", text="secret detail")
        scene = RecallScene("s1", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.FULL)
    def test_cross_session_same_subject_is_paraphrase(self):
        art = _memory(subject="owner", scope="private", text="secret detail")
        scene = RecallScene("s2", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertEqual(got.level, DisclosureLevel.PARAPHRASE)
        self.assertNotIn("secret detail", safe_text(art, got.level))
    def test_absent_third_party_and_shadow_are_not_full(self):
        art = _memory(subject="other", scope="shadow", text="secret")
        scene = RecallScene("s2", "owner", "owner", ("owner",))
        got = decide(art, scene, 1.0, origin_sessions=("s1",))
        self.assertIn(got.level, (DisclosureLevel.HINT, DisclosureLevel.SILENCE))


if __name__ == "__main__":
    unittest.main()
