"""Source evidence ranking and repository scope regressions."""

from __future__ import annotations

import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.source import Source
from recall.source_query import SourceHit, query_recent


NOW = datetime.datetime(2026, 10, 25, 12, 0, 0)


def source(source_id: str, text: str, *, session="s1", speaker="u1",
           role="user", at="2026-10-25T11:00:00") -> Source:
    return Source(source_id, f"turn-{source_id}", session, speaker, role, text, at)


class SourceQueryTest(unittest.TestCase):
    def test_lexical_match_beats_unrelated_recency(self):
        rows = [
            source("old", "quantum trading notes", at="2026-10-25T09:00:00"),
            source("new", "lunch menu", at="2026-10-25T11:59:00"),
        ]
        hits = query_recent(
            "quantum trading", rows, session_id="s1", speaker="u1", now=NOW
        )
        self.assertEqual(hits[0].source_id, "old")
        self.assertGreater(hits[0].lexical, 0)
        self.assertTrue(hits[0].same_session)

    def test_recency_breaks_equal_lexical_ties(self):
        for zone in (None, datetime.timezone.utc,
                     datetime.timezone(datetime.timedelta(hours=8))):
            with self.subTest(zone=zone):
                rows = []
                for source_id, hours in (("a-old", 11), ("z-new", 1)):
                    stamp = NOW - datetime.timedelta(hours=hours)
                    if zone is not None:
                        stamp = stamp.astimezone(zone)
                    rows.append(source(source_id, "quantum trading notes",
                                       at=stamp.isoformat()))
                hits = query_recent(
                    "quantum trading", rows, session_id="s1", speaker="u1", now=NOW
                )
                self.assertEqual(hits[0].source_id, "z-new")

    def test_equivalent_instants_have_equal_recency(self):
        stamp = NOW - datetime.timedelta(hours=1)
        rows = [source("local", "quantum trading notes", at=stamp.isoformat())]
        for hours in (0, 8):
            zone = datetime.timezone(datetime.timedelta(hours=hours))
            rows.append(source(str(hours), "quantum trading notes",
                               at=stamp.astimezone(zone).isoformat()))
        for now in (NOW, NOW.astimezone(datetime.timezone.utc)):
            with self.subTest(now=now):
                hits = query_recent("quantum trading", rows, now=now)
                for hit in hits[1:]:
                    self.assertAlmostEqual(hit.score, hits[0].score)

    def test_clock_and_empty_queries_do_not_match_source(self):
        rows = [source("s1", "quantum trading")]
        self.assertEqual(
            query_recent("what time is it", rows, session_id="s1", now=NOW), []
        )
        self.assertEqual(
            query_recent("\u73b0\u5728\u51e0\u70b9", rows, session_id="s1", now=NOW),
            [],
        )
        self.assertEqual(query_recent("", rows, session_id="s1", now=NOW), [])

    def test_current_query_text_is_excluded(self):
        rows = [source("s1", "quantum trading")]
        self.assertEqual(
            query_recent("quantum trading", rows, session_id="s1", now=NOW), []
        )

    def test_explicit_recall_can_use_recent_source_without_lexical_match(self):
        rows = [source("s1", "unrelated recent note", at="2026-10-25T11:00:00")]
        hits = query_recent(
            "remember what we talked about", rows, session_id="s1", now=NOW
        )
        self.assertEqual([item.source_id for item in hits], ["s1"])

    def test_cross_session_source_is_evidence_only(self):
        rows = [source("s1", "cross session quantum", session="other")]
        hits = query_recent(
            "quantum trading", rows, session_id="s1", speaker="u1", now=NOW
        )
        self.assertEqual([item.source_id for item in hits], ["s1"])
        self.assertFalse(hits[0].same_session)
        self.assertFalse(hasattr(hits[0], "text"))

    def test_limit_is_bounded(self):
        rows = [
            source(f"s{index}", "quantum trading notes")
            for index in range(5)
        ]
        hits = query_recent(
            "quantum trading", rows, session_id="s1", now=NOW, limit=2
        )
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(isinstance(item, SourceHit) for item in hits))


class RepositoryPortTest(unittest.TestCase):
    def test_recent_sources_and_revision_scoped_artifact_lookup(self):
        from core.artifact import Lineage, make, revise
        from store import open_store

        db = open_store(":memory:")
        self.addCleanup(db.close)
        one = source("s1", "recent source", at="2026-10-25T11:00:00")
        two = source("s2", "revised source", at="2026-10-25T11:01:00")
        db.sources.append_sources([one, two])
        self.assertEqual(
            [item.id for item in db.sources.recent_sources(
                since="2026-10-25T00:00:00", limit=10
            )],
            ["s2", "s1"],
        )
        art = make(
            "memory", {"text": "derived memory", "level": "fact"},
            scope="shared", subject_id="u1",
            lineage=Lineage(sources=("s1",)),
        )
        db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        self.assertEqual(
            [item.header.id for item in db.artifacts.by_source_ids(["s1"])],
            [art.header.id],
        )
        revised = revise(art, payload={"text": "second revision", "level": "fact"})
        db.artifacts.commit(
            revised,
            expected_revision=art.header.revision,
            op="revise",
            source_ids=("s2",),
        )
        self.assertEqual(db.artifacts.by_source_ids(["s1"]), [])
        self.assertEqual(
            [item.header.id for item in db.artifacts.by_source_ids(["s2"])],
            [art.header.id],
        )
        self.assertEqual(db.artifacts.by_source_ids([]), [])


if __name__ == "__main__":
    unittest.main()
