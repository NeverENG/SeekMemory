"""Tree reads and writes preserve storage, evidence and cache behavior."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import Artifact, make, revise
from core.source import Source
from core.versioning import VersionError
from store import open_store
from store.cache import Cache
from services import TreeService


class TreeServiceContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.tree = TreeService(self.db.artifacts, self.cache)
        self.source = Source("s_tree", "turn_tree", "session_tree", "u1", "user", "a fact")
        self.db.sources.append_sources([self.source])

    def memory(self, text: str, level: str = "scene", **header: object) -> Artifact:
        return make("memory", {"text": text, "level": level},
                    lineage={"sources": (self.source.id,)}, **header)

    def save(self, art: Artifact) -> None:
        self.db.artifacts.commit(art, expected_revision=0, op="create",
                                 source_ids=art.header.lineage.sources)

    def test_children_prefer_cache_and_fall_back_to_storage_without_writes(self) -> None:
        parent = self.memory("parent", "impression")
        cached, uncached = self.memory("cached"), self.memory("uncached")
        for art in (parent, cached, uncached):
            self.save(art)
        kind = "tree_child:" + parent.header.id
        for child in (cached, uncached):
            self.db.artifacts.add_edge(parent.header.id, child.header.id, kind, 1.0)
        self.db.artifacts.add_edge(parent.header.id, "missing", kind, 1.0)
        self.db.artifacts.add_edge(parent.header.id, "unrelated", "causal", 1.0)
        updated = revise(cached, {"text": "cached view", "level": "scene"})
        self.cache.put(updated)
        ledger_hash, cache_version = self.db.ledger.last_hash(), self.cache.version

        got = {art.header.id: art for art in self.tree.children(parent.header.id)}

        self.assertEqual(got, {cached.header.id: updated, uncached.header.id: uncached})
        self.assertEqual(self.tree.children(""), [])
        self.assertEqual(self.tree.children("missing"), [])
        self.assertEqual(self.db.artifacts.get(cached.header.id), cached)
        self.assertIsNone(self.cache.get(uncached.header.id))
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)
        self.assertEqual(self.cache.version, cache_version)
        self.assertEqual(TreeService(self.db.artifacts).children(parent.header.id),
                         [self.db.artifacts.get(art.header.id)
                          for art in self.tree.children(parent.header.id)])

    def test_parent_and_ancestors_follow_existing_edges_without_writes(self) -> None:
        root, middle, leaf = (self.memory(name) for name in ("root", "middle", "leaf"))
        self.tree.add_under(root, None)
        self.tree.add_under(middle, root.header.id)
        self.tree.add_under(leaf, middle.header.id)
        before = self.db.ledger.last_hash()
        self.assertEqual(self.tree.parent_id(leaf.header.id), middle.header.id)
        self.assertEqual(self.tree.ancestor_ids(leaf.header.id),
                         (middle.header.id, root.header.id))
        self.assertEqual(self.tree.ancestor_ids(leaf.header.id, max_depth=1),
                         (middle.header.id,))
        self.assertEqual(self.db.ledger.last_hash(), before)

    def test_impressions_fall_back_only_when_the_cache_level_is_empty(self) -> None:
        first, second = self.memory("first", "impression"), self.memory("second", "impression")
        for art in (first, second, self.memory("scene"),
                    self.memory("forgotten", "impression", state="forgotten"),
                    make("persona", {"text": "persona", "level": "impression"})):
            self.save(art)
        expected = {first.header.id, second.header.id}
        for tree in (self.tree, TreeService(self.db.artifacts)):
            self.assertEqual({art.header.id for art in tree.impressions()}, expected)

        self.cache.put(first)
        self.assertEqual(self.tree.impressions(), [first])
        self.cache.put(make("persona", {"text": "not memory", "level": "impression"}))
        self.assertEqual(self.tree.impressions(), [first])

    def test_add_under_creates_version_evidence_ledger_and_relation(self) -> None:
        parent, child = self.memory("parent", "impression"), self.memory("child")
        self.save(parent)

        self.assertIs(self.tree.add_under(child, parent.header.id), child)

        self.assertEqual(self.db.artifacts.get(child.header.id), child)
        self.assertEqual(self.cache.get(child.header.id), child)
        self.assertEqual(self.tree.children(parent.header.id), [child])
        self.assertEqual([(v["revision"], v["op"]) for v in self.db.artifacts.history(child.header.id)],
                         [(1, "create")])
        self.assertEqual([art.header.id for art in self.db.artifacts.by_source_ids([self.source.id])],
                         [art.header.id for art in self.db.artifacts.list(state="active")])
        record = self.db.artifacts.inspect_record(child.header.id)
        self.assertEqual([source["id"] for source in record["sources"]], [self.source.id])
        entry = self.db.ledger.entries()[-1]
        self.assertEqual((entry["entity"], entry["op"], entry["reason"]),
                         (child.header.id, "create", "tree"))
        self.assertTrue(self.db.ledger.verify())

    def test_existing_child_is_revised_but_the_original_input_is_returned(self) -> None:
        child = self.memory("old")
        self.save(child)
        self.cache.put(child)
        incoming = Artifact(child.header, {"text": "new", "level": "detail"})

        self.assertIs(self.tree.add_under(incoming, None), incoming)

        stored = self.db.artifacts.get(child.header.id)
        self.assertEqual(stored.header.revision, 2)
        self.assertEqual(stored.payload, incoming.payload)
        self.assertEqual(stored.header.time.created, child.header.time.created)
        self.assertEqual(self.cache.get(child.header.id), stored)
        self.assertEqual([(v["revision"], v["op"]) for v in self.db.artifacts.history(child.header.id)],
                         [(1, "create"), (2, "revise")])
        self.assertEqual(self.db.artifacts.by_source_ids([self.source.id]), [stored])
        self.assertEqual(self.db.ledger.entries()[-1]["op"], "revise")
        self.assertTrue(self.db.ledger.verify())

    def test_revising_without_cache_preserves_the_supplied_next_revision(self) -> None:
        child = self.memory("old")
        self.save(child)
        incoming = revise(child, {"text": "new", "level": "detail"})

        self.assertIs(TreeService(self.db.artifacts).add_under(incoming, None), incoming)

        self.assertEqual(self.db.artifacts.get(child.header.id), incoming)
        self.assertEqual(self.db.artifacts.edges_of(child.header.id), [])

    def test_self_parent_is_rejected_before_any_write(self) -> None:
        child = self.memory("child")
        ledger_hash, cache_version = self.db.ledger.last_hash(), self.cache.version

        with self.assertRaisesRegex(ValueError, "own parent"):
            self.tree.add_under(child, child.header.id)

        self.assertIsNone(self.db.artifacts.get(child.header.id))
        self.assertIsNone(self.cache.get(child.header.id))
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)
        self.assertEqual(self.cache.version, cache_version)

    def test_invalid_revision_leaves_storage_cache_and_relations_unchanged(self) -> None:
        parent, child = self.memory("parent", "impression"), self.memory("old")
        self.save(parent)
        self.save(child)
        self.cache.put(child)
        invalid = revise(child, revision=4)
        ledger_hash, cache_version = self.db.ledger.last_hash(), self.cache.version

        with self.assertRaises(VersionError):
            self.tree.add_under(invalid, parent.header.id)

        self.assertEqual(self.db.artifacts.get(child.header.id), child)
        self.assertEqual(self.cache.get(child.header.id), child)
        self.assertEqual(len(self.db.artifacts.history(child.header.id)), 1)
        self.assertEqual(self.tree.children(parent.header.id), [])
        self.assertEqual(self.db.ledger.last_hash(), ledger_hash)
        self.assertEqual(self.cache.version, cache_version)


if __name__ == "__main__":
    unittest.main()
