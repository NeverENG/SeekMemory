"""Resolve model role labels only from the candidate's own user evidence.

仅以候选自身的用户证据解析模型角色标签，不改认其他主体。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import DialogueTurn
from perceive.absorb import build_plan

SESSION = "test:FriendMessage:u1"


def turn(speaker: str = "u1", source: str = "s1", *, role: str = "user",
         session: str = SESSION) -> DialogueTurn:
    return DialogueTurn(session, speaker, role, "synthetic preference",
                        "2026-10-31T12:00:00+08:00", source)


def item(subject: str, kind: str = "speaker", **extra) -> dict:
    return {"level": "fact", "text": "喜欢茉莉花茶，不加糖", "tags": "饮料 偏好 糖",
            "subject_id": subject, "subject_kind": kind, **extra}


class SubjectNormalizationTest(unittest.TestCase):
    def plan(self, rows: list[dict], turns=None, context=None):
        turns = [turn()] if turns is None else turns
        context = turns if context is None else context
        result = build_plan(turns, context, json.dumps(rows), None, owner_id="u1")
        self.assertFalse(result.errors)
        self.assertIsNone(result.outcome)
        return result.artifacts

    def test_verified_user_wrapper_matches_header_and_payload(self) -> None:
        for kind in ("owner", "speaker", "third_party", ""):
            with self.subTest(kind=kind):
                art, = self.plan([item("user(u1)", kind, evidence_source_ids=["s1"])])
                self.assertEqual(art.header.subject_id, "u1")
                self.assertEqual(art.payload["subject_id"], "u1")
                self.assertEqual(art.header.lineage.sources, ("s1",))

    def test_ordinary_fact_without_citations_uses_only_current_input_sources(self) -> None:
        art, = self.plan([item("user(u1)")])
        self.assertEqual(art.header.subject_id, "u1")
        other = turn("u2", "s2")
        art, = self.plan([item("user(u2)")], context=[turn(), other])
        self.assertEqual(art.header.subject_id, "user(u2)")

    def test_group_keeps_each_verified_speaker_distinct(self) -> None:
        session = "test:GroupMessage:g1"
        turns = [turn("u1", "s1", session=session), turn("u2", "s2", session=session)]
        arts = self.plan([
            item("user(u1)", evidence_source_ids=["s1"]),
            item("user(u2)", evidence_source_ids=["s2"]),
        ], turns)
        self.assertEqual({art.header.subject_id for art in arts}, {"u1", "u2"})
        self.assertTrue(all(art.header.scope == "shared" for art in arts))

    def test_wrong_citation_cannot_borrow_another_user_identity(self) -> None:
        turns = [turn(), turn("u2", "s2")]
        art, = self.plan([item("user(u2)", evidence_source_ids=["s1"])], turns)
        self.assertEqual(art.header.subject_id, "user(u2)")

    def test_assistant_or_foreign_session_is_not_user_identity_evidence(self) -> None:
        for context in (
            [turn(role="assistant")],
            [turn(session="test:FriendMessage:elsewhere")],
        ):
            with self.subTest(context=context):
                art, = self.plan([item("user(u1)")], context=context)
                self.assertEqual(art.header.subject_id, "user(u1)")

    def test_legacy_source_less_input_does_not_gain_verified_identity(self) -> None:
        art, = self.plan([item("user(u1)")], [turn(source="")])
        self.assertEqual(art.header.subject_id, "user(u1)")
        self.assertTrue(art.payload["legacy_no_source"])

    def test_unknown_malformed_and_non_user_wrappers_stay_unresolved(self) -> None:
        for value in ("user(unknown)", "user(user(u1))", "user(u1) suffix",
                      "user()", "User(u1)", "assistant(u1)", "user( u1 )"):
            with self.subTest(value=value):
                art, = self.plan([item(value, "owner")])
                self.assertEqual(art.header.subject_id, value)

    def test_reserved_and_explicit_third_party_subjects_keep_their_meaning(self) -> None:
        for subject, kind, expected in (
            ("owner", "owner", "u1"), ("speaker", "speaker", "u1"),
            ("self", "self", "self"), ("world", "world", "world"),
            ("relation", "relation", "relation"),
            ("third:小林", "third_party", "third:小林"),
            ("u2", "third_party", "u2"),
            ("user(u1)", "self", "user(u1)"),
            ("user(u1)", "world", "user(u1)"),
            ("user(u1)", "relation", "user(u1)"),
        ):
            with self.subTest(subject=subject, kind=kind):
                art, = self.plan([item(subject, kind)])
                self.assertEqual(art.header.subject_id, expected)

    def test_wrapped_reserved_tokens_do_not_become_special_subjects(self) -> None:
        for subject in ("owner", "speaker", "self", "world", "relation"):
            with self.subTest(subject=subject):
                wrapped = f"user({subject})"
                art, = self.plan([item(wrapped)], [turn(subject)])
                self.assertEqual(art.header.subject_id, wrapped)

    def test_equivalent_wrapped_and_bare_subjects_share_deduplication(self) -> None:
        arts = self.plan([item("user(u1)"), item("u1")])
        self.assertEqual(len(arts), 1)
        self.assertEqual(arts[0].header.subject_id, "u1")


if __name__ == "__main__":
    unittest.main()
