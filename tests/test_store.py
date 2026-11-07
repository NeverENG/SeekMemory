"""test_store：SQLite 持久化、内存缓存与追加日志哈希链。

覆盖 upsert/get 全字段往返、list 过滤、edges 双向查询、账本链连续与
篡改检测，以及 Cache 的 put/get/active/by_level/remove。
"""

from __future__ import annotations

import io
import asyncio
import json
import datetime
import os
import sqlite3
import shutil
import sys
import tempfile
import unittest

from contextlib import contextmanager, nullcontext
from types import SimpleNamespace
from contextlib import redirect_stdout
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, make, revise
from core.relationship import relationship_id
from core.relationship_rules import RelationshipCandidate, RelationshipReason, RelationshipStrength, ConversationScope, VERIFIER_VERSION, relationship_event_id
from core.source import Source
from store.cache import Cache
from store import Store, open_store
from adapters.relationship_policy import RelationshipReader
from maintain.relationship import consolidate_relationships, migrate_v1_candidates
from services.maintenance_service import MaintenanceService
from scripts.deactivate_relationships import main as deactivate_relationships_main
from store.ledger import chain_hash, chain_payload
from store.ledger import Ledger


def _memory(text: str, level: str = "scene", **header_kw: object) -> Artifact:
    """构造一条最小合法 memory，header_kw 原样透传给 make。"""
    payload = {
        "text": text,
        "level": level,
        "shape": "point",
        "chrono": "once",
        "about": "other",
    }
    return make("memory", payload, **header_kw)


def _example() -> Artifact:
    """构造一条最小合法 example。"""
    return make("example", {"user": "你好", "assistant": "嗨"})


def _edges(db: Store, node_id: str) -> list[tuple[str, str, float]]:
    """把边权四舍五入到 6 位，避免浮点比较噪声。"""
    return [(other, kind, round(weight, 6)) for other, kind, weight in db.artifacts.edges_of(node_id)]


class _StoreCase(unittest.TestCase):
    """每个用例一个临时数据库，跑完关闭连接并删除目录。"""

    def setUp(self) -> None:
        """创建临时数据库与缓存。"""
        self.tmpdir = tempfile.mkdtemp(prefix="seekmemory_store_")
        self.db = open_store(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db.artifacts)

    def tearDown(self) -> None:
        """关闭数据库并删除临时目录。"""
        self.db.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


class DBTest(_StoreCase):
    """DB：节点往返、过滤与关系边。"""

    def test_upsert_get_roundtrip_all_fields(self) -> None:
        """upsert 后 get 能无损还原 header 与 payload 的所有字段。"""
        art = make(
            "memory",
            {
                "text": "他加班到很晚", "level": "scene", "shape": "periodic",
                "chrono": "periodic", "about": "relation", "first": True,
            },
            revision=4,
            state="active",
            scope="shared",
            said_by="owner",
            shareable="private_only",
            strength={
                "weight": 2.0, "confidence": 0.9, "arousal": 0.8,
                "valence": -0.5, "funny": 0.3, "hits": 7,
            },
            time={
                "created": "2020-01-01T01:02:03", "updated": "2020-02-03T04:05:06",
                "valid_from": "2020-01-01", "valid_to": "2020-12-31",
                "expires": "2021-01-01",
            },
            lineage={"sources": ("s_1", "s_2"), "derived_from": ("n_x",)},
        )
        self.db.artifacts.upsert(art)
        got = self.db.artifacts.get(art.header.id)
        self.assertIsNotNone(got)
        self.assertEqual(art, got)
        self.assertEqual(got.header.lineage.sources, ("s_1", "s_2"))
        self.assertEqual(got.header.lineage.derived_from, ("n_x",))
        self.assertIsNone(self.db.artifacts.get("n_missing"))

    def test_upsert_updates_existing_row(self) -> None:
        """同 id 再次 upsert 是更新而不是插入，created 保持不变。"""
        art = _memory("旧文本")
        self.db.artifacts.upsert(art)
        revised = revise(art, {"text": "新文本", "level": "detail"}, strength={"weight": 2.5})
        self.db.artifacts.upsert(revised)
        got = self.db.artifacts.get(art.header.id)
        self.assertEqual(got.header.revision, 2)
        self.assertEqual(got.payload["text"], "新文本")
        self.assertEqual(got.payload["level"], "detail")
        self.assertEqual(got.header.strength.weight, 2.5)
        self.assertEqual(got.header.time.created, art.header.time.created)
        self.assertEqual(self.db.artifacts.count("memory"), 1)

    def test_list_filters_family_and_state(self) -> None:
        """list 可按 family、state 单独或组合过滤。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        example = _example()
        for art in (scene, fact, example):
            self.db.artifacts.upsert(art)
        forgotten = revise(scene, state="forgotten")
        self.db.artifacts.upsert(forgotten)

        self.assertEqual({a.header.id for a in self.db.artifacts.list()}, {scene.header.id, fact.header.id, example.header.id})
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory")},
            {scene.header.id, fact.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory", state="active")},
            {fact.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.db.artifacts.list(family="memory", state="forgotten")},
            {scene.header.id},
        )
        self.assertEqual(len(self.db.artifacts.list(state="active")), 2)
        self.assertEqual(self.db.artifacts.list(family="persona"), [])
        self.assertEqual(self.db.artifacts.count(), 3)
        self.assertEqual(self.db.artifacts.count("memory"), 2)


    def test_relationship_rollback_forgets_heads_and_preserves_audit(self) -> None:
        source = Source(
            "rollback-source", "rollback-turn", "bot:FriendMessage:u1",
            "u1", "user", "fixture", "2026-10-26T12:00:00",
        )
        self.db.sources.append_sources([source])
        relation = make(
            "relationship",
            {
                "summary": "关系状态：冷淡",
                "affinity": -0.3,
                "confidence": 0.8,
                "evidence_count": 4,
                "relation_band": "low",
                "policy": {
                    "version": "relationship-v1",
                    "private_weight": 1.0,
                    "group_weight": 0.5,
                    "learning_rate": 0.25,
                    "max_revision_delta": 0.1,
                },
            },
            subject_id="u1",
            lineage={"sources": (source.id,)},
        )
        self.db.artifacts.commit(
            relation, expected_revision=0, op="create", source_ids=(source.id,)
        )
        output = io.StringIO()
        with redirect_stdout(output):
            code = deactivate_relationships_main([
                "--db", os.path.join(self.tmpdir, "memory.db"), "--confirmed",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(output.getvalue(), "active=1 forgotten=1 failed=0\n")
        head = self.db.artifacts.get(relation.header.id)
        self.assertEqual(head.header.state, "forgotten")
        self.assertEqual(
            [row["revision"] for row in self.db.artifacts.history(relation.header.id)],
            [1, 2],
        )
        self.assertEqual(
            self.db.sources.sources_by_ids([source.id])[source.id].text,
            "fixture",
        )
        entries = [
            row for row in self.db.ledger.entries()
            if row["entity"] == relation.header.id
        ]
        self.assertEqual([row["op"] for row in entries], ["create", "forget"])
        self.assertNotIn(source.id, output.getvalue())
    def test_edges_of_returns_both_directions(self) -> None:
        """edges_of 从边的任意一端都能查到，另一端与权重正确。"""
        left, right, third = _memory("甲"), _memory("乙"), _memory("丙")
        for art in (left, right, third):
            self.db.artifacts.upsert(art)
        self.db.artifacts.add_edge(left.header.id, right.header.id, "similar", 0.7)
        self.db.artifacts.add_edge(left.header.id, third.header.id, "causal", 0.5)

        self.assertIn((right.header.id, "similar", 0.7), _edges(self.db, left.header.id))
        self.assertIn((third.header.id, "causal", 0.5), _edges(self.db, left.header.id))
        self.assertEqual(_edges(self.db, right.header.id), [(left.header.id, "similar", 0.7)])
        self.assertEqual(_edges(self.db, third.header.id), [(left.header.id, "causal", 0.5)])
        self.assertEqual(_edges(self.db, "n_missing"), [])

        self.db.artifacts.add_edge(left.header.id, right.header.id, "similar", 0.9)
        similar = [edge for edge in _edges(self.db, left.header.id) if edge[0] == right.header.id]
        self.assertEqual(similar, [(right.header.id, "similar", 0.9)])

    def test_multi_parent_edges_are_bounded_and_legacy_only_rows_detected(self) -> None:
        child = _memory("child", "scene")
        first, second = _memory("first", "impression"), _memory("second", "impression")
        for art in (first, second, child):
            self.db.artifacts.upsert(art)
        for parent in (first, second):
            self.db.artifacts.add_edge(parent.header.id, child.header.id,
                                       "tree_child:" + parent.header.id, 1.0)
        self.assertEqual(set(self.db.artifacts.tree_parents(child.header.id, 2)),
                         {first.header.id, second.header.id})
        self.assertEqual(len(self.db.artifacts.tree_parents(child.header.id, 1)), 1)
        self.assertEqual(self.db.artifacts.tree_children(first.header.id, 1), [child.header.id])
        self.assertEqual(self.db.artifacts.legacy_tree_gap_count(), 0)
        self.db.conn.execute("UPDATE nodes SET parent = ? WHERE id = ?",
                             ("missing_legacy_edge", child.header.id))
        self.assertEqual(self.db.artifacts.legacy_tree_gap_count(), 1)

    def test_ledger_chain_is_continuous(self) -> None:
        """账本从空链开始，逐条 prev 指向上一条 self，整链可验证。"""
        ledger = Ledger(self.db.ledger)
        self.assertTrue(ledger.verify())
        self.assertEqual(ledger.last_hash(), "")

        first = ledger.append("create", "n_1", None, "h_1", "创建")
        second = ledger.append("update", "n_1", "h_1", "h_2", "修改")
        third = ledger.append("forget", "n_2", "h_3", None, "遗忘")
        self.assertEqual(ledger.last_hash(), third)

        entries = self.db.ledger.entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["prev_hash"], "")
        self.assertEqual(entries[0]["self_hash"], first)
        self.assertEqual(entries[1]["prev_hash"], first)
        self.assertEqual(entries[1]["self_hash"], second)
        self.assertEqual(entries[2]["prev_hash"], second)
        self.assertEqual(entries[2]["self_hash"], third)

        payload = chain_payload(
            str(entries[1]["at"]),
            str(entries[1]["op"]),
            str(entries[1]["entity"]),
            entries[1]["before_hash"],
            entries[1]["after_hash"],
            str(entries[1]["reason"]),
        )
        self.assertEqual(chain_hash(first, payload), second)
        self.assertTrue(ledger.verify())

    def test_ledger_tamper_detected(self) -> None:
        """改动账本任意字段后 verify 返回 False。"""
        ledger = Ledger(self.db.ledger)
        ledger.append("create", "n_1", None, "h_1", "创建")
        ledger.append("update", "n_1", "h_1", "h_2", "修改")
        self.assertTrue(ledger.verify())

        with self.db.conn:
            self.db.conn.execute("UPDATE ledger SET reason = '被改过' WHERE seq = 1")
        self.assertFalse(ledger.verify())

    def test_ledger_prev_tamper_detected(self) -> None:
        """只改 prev_hash 破坏连续性，同样能被检出。"""
        ledger = Ledger(self.db.ledger)
        ledger.append("create", "n_1", None, "h_1", "创建")
        ledger.append("update", "n_1", "h_1", "h_2", "修改")
        with self.db.conn:
            self.db.conn.execute("UPDATE ledger SET prev_hash = 'deadbeef' WHERE seq = 2")
        self.assertFalse(ledger.verify())


class CacheTest(_StoreCase):
    """Cache：热数据索引与移除。"""

    def test_put_get_active_by_level(self) -> None:
        """put 后可 get，active 按 family 过滤，by_level 按 level 过滤。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        example = _example()
        for art in (scene, fact, example):
            self.cache.put(art)

        self.assertEqual(self.cache.size(), 3)
        self.assertIs(self.cache.get(scene.header.id), scene)
        self.assertEqual(
            {a.header.id for a in self.cache.active()},
            {scene.header.id, fact.header.id, example.header.id},
        )
        self.assertEqual(
            {a.header.id for a in self.cache.active("memory")},
            {scene.header.id, fact.header.id},
        )
        self.assertEqual([a.header.id for a in self.cache.active("example")], [example.header.id])
        self.assertEqual(self.cache.active("persona"), [])
        self.assertEqual([a.header.id for a in self.cache.by_level("scene")], [scene.header.id])
        self.assertEqual([a.header.id for a in self.cache.by_level("fact")], [fact.header.id])
        self.assertEqual(self.cache.by_level("impression"), [])

    def test_put_non_active_removes_from_cache(self) -> None:
        """put 一条非 active 的同 id 记忆时，把它从缓存里移除。"""
        scene = _memory("场景", "scene")
        self.cache.put(scene)
        self.cache.put(revise(scene, state="forgotten"))
        self.assertIsNone(self.cache.get(scene.header.id))
        self.assertEqual(self.cache.size(), 0)
        self.assertEqual(self.cache.by_level("scene"), [])

    def test_put_reindexes_level(self) -> None:
        """同 id 改了 level 后再 put，旧 level 索引会被清理。"""
        art = _memory("场景", "scene")
        self.cache.put(art)
        moved = revise(art, {"text": "细化", "level": "detail"})
        self.cache.put(moved)
        self.assertIs(self.cache.get(art.header.id), moved)
        self.assertEqual(self.cache.by_level("scene"), [])
        self.assertEqual([a.header.id for a in self.cache.by_level("detail")], [art.header.id])

    def test_remove_cleans_indexes(self) -> None:
        """remove 同时清理 family 与 level 索引，重复移除不报错。"""
        scene = _memory("场景", "scene")
        fact = _memory("事实", "fact")
        self.cache.put(scene)
        self.cache.put(fact)
        self.cache.remove(scene.header.id)
        self.assertIsNone(self.cache.get(scene.header.id))
        self.assertEqual(self.cache.size(), 1)
        self.assertEqual(self.cache.by_level("scene"), [])
        self.assertEqual([a.header.id for a in self.cache.active("memory")], [fact.header.id])
        self.cache.remove(scene.header.id)
        self.cache.remove("n_missing")
        self.assertEqual(self.cache.size(), 1)

    def test_load_only_active_from_db(self) -> None:
        """load 清空旧内容，只载入数据库里 state=active 的记忆。"""
        active = _memory("活跃", "scene")
        forgotten = _memory("遗忘", "scene")
        example = _example()
        self.db.artifacts.upsert(active)
        self.db.artifacts.upsert(forgotten)
        self.db.artifacts.upsert(revise(forgotten, state="forgotten"))
        self.db.artifacts.upsert(example)

        stray = _memory("只在缓存里")
        self.cache.put(stray)
        self.cache.load()

        self.assertEqual(
            {a.header.id for a in self.cache.active()},
            {active.header.id, example.header.id},
        )
        self.assertIsNone(self.cache.get(stray.header.id))
        self.assertEqual(self.cache.size(), 2)


class RelationshipV2PersistenceTest(_StoreCase):
    """Verified evidence projects into versioned heads without losing history."""

    def _source(self, source_id: str, text: str, *, session: str = "bot:FriendMessage:u1") -> Source:
        source = Source(source_id, source_id, session, "u1", "user", text,
                        "2026-10-26T12:00:00+00:00")
        self.db.sources.append_sources([source])
        return source

    def _verified(self, source: Source, reason: RelationshipReason) -> None:
        candidate = RelationshipCandidate(
            source.speaker_id, reason, RelationshipStrength.STRONG, source.id,
            (source.id,), source.session_id, ConversationScope.PRIVATE,
        )
        event_id = relationship_event_id(candidate)
        self.db.relationship_events.record_pending({
            "event_id": event_id, "verifier_version": VERIFIER_VERSION,
            "subject_id": source.speaker_id, "reason": reason.value,
            "strength": candidate.strength.value, "scope": candidate.scope.value,
            "event_at": source.at, "primary_source_id": source.id,
            "source_ids": (source.id,),
        })
        self.db.relationship_events.decide(event_id, VERIFIER_VERSION, "verified")

    def test_pending_current_verifier_skips_old_version_backlog(self) -> None:
        source = self._source("versioned", "鱼，谢谢你")
        for index in range(24):
            self.db.relationship_events.record_pending({
                "event_id": f"old-{index:02d}", "verifier_version": "relationship-verifier-v1",
                "subject_id": "u1", "reason": "gratitude", "strength": "strong",
                "scope": "private", "event_at": source.at,
                "primary_source_id": source.id, "source_ids": (source.id,),
            })
        self.db.relationship_events.record_pending({
            "event_id": "current", "verifier_version": VERIFIER_VERSION,
            "subject_id": "u1", "reason": "gratitude", "strength": "strong",
            "scope": "private", "event_at": source.at,
            "primary_source_id": source.id, "source_ids": (source.id,),
        })
        self.assertEqual(
            [row.event_id for row in self.db.relationship_events.pending(1, VERIFIER_VERSION)],
            ["current"],
        )
        self.assertEqual(len(self.db.relationship_events.pending(30)), 25)

    def test_failed_first_24_do_not_starve_next_candidate_after_restart(self) -> None:
        moment = [datetime.datetime(2026, 10, 26, 12, 5, tzinfo=datetime.timezone.utc)]
        for index in range(25):
            source_id = f"s{index:02d}"
            at = (moment[0].replace(minute=0) + datetime.timedelta(seconds=index)).isoformat()
            source = Source(source_id, source_id, "bot:FriendMessage:u1", "u1", "user", "鱼，谢谢你", at)
            self.db.sources.append_sources([source])
            self.db.relationship_events.record_pending({
                "event_id": f"e{index:02d}", "verifier_version": VERIFIER_VERSION,
                "subject_id": "u1", "reason": "gratitude", "strength": "strong",
                "scope": "private", "event_at": at,
                "primary_source_id": source_id, "source_ids": (source_id,),
            })

        class Provider:
            def __init__(self) -> None:
                self.calls: list[str] = []
                self.fail = True

            async def text_chat(self, *, prompt: str, **_kwargs):
                source_id = json.loads(prompt)["candidate"]["primary_source_id"]
                self.calls.append(source_id)
                if self.fail and source_id != "s24":
                    raise RuntimeError("model unavailable")
                return SimpleNamespace(completion_text=json.dumps({
                    "reason": "gratitude", "source_ids": [source_id],
                    "target": "assistant", "decision": "verified",
                }))

        provider = Provider()

        async def provider_for(_session):
            return provider

        def service() -> MaintenanceService:
            journal = SimpleNamespace(span=lambda *_a, **_kw: nullcontext({}), record=lambda *_a, **_kw: None)
            logger = SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None)
            return MaintenanceService(
                artifacts=self.db.artifacts, sources=self.db.sources, cache=self.cache,
                journal=journal, task_id=lambda: "weekly", logger=logger,
                clock=lambda: moment[0], relationship_events=self.db.relationship_events,
                provider_for=provider_for,
            )

        asyncio.run(service().weekly())
        self.assertEqual(provider.calls, [f"s{index:02d}" for index in range(24)])
        self.assertEqual(
            next(row for row in self.db.relationship_events.by_subject("u1", VERIFIER_VERSION)
                 if row.event_id == "e00").retry_count,
            1,
        )
        self.db.close()
        self.db = open_store(os.path.join(self.tmpdir, "memory.db"))
        self.cache = Cache(self.db.artifacts)
        resumed = service()
        asyncio.run(resumed.weekly())
        self.assertEqual(provider.calls[-1], "s24")
        self.assertEqual(len(provider.calls), 25)
        self.assertEqual(
            next(row for row in self.db.relationship_events.by_subject("u1", VERIFIER_VERSION)
                 if row.event_id == "e24").status,
            "verified",
        )
        provider.fail = False
        moment[0] += datetime.timedelta(minutes=1)
        asyncio.run(resumed.weekly())
        self.assertEqual(self.db.relationship_events.pending(30), ())

    def test_old_relationship_event_table_upgrades_without_losing_pending_rows(self) -> None:
        path = os.path.join(self.tmpdir, "memory.db")
        self.db.close()
        with sqlite3.connect(path) as conn:
            conn.execute("DROP TABLE relationship_events")
            conn.execute(
                "CREATE TABLE relationship_events ("
                "event_id TEXT NOT NULL, verifier_version TEXT NOT NULL, subject_id TEXT NOT NULL, "
                "reason TEXT NOT NULL, strength TEXT NOT NULL, scope TEXT NOT NULL, "
                "event_at TEXT NOT NULL, primary_source_id TEXT NOT NULL, source_ids TEXT NOT NULL, "
                "repair_of TEXT NOT NULL DEFAULT '', origin_artifact_id TEXT NOT NULL DEFAULT '', "
                "origin_revision INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, "
                "created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT '', "
                "PRIMARY KEY (event_id, verifier_version))"
            )
            conn.execute(
                "INSERT INTO relationship_events (event_id, verifier_version, subject_id, reason, "
                "strength, scope, event_at, primary_source_id, source_ids, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("old-event", VERIFIER_VERSION, "u1", "gratitude", "strong", "private",
                 "2026-10-26T12:00:00+00:00", "source", '["source"]', "pending",
                 "2026-10-26T12:00:00"),
            )
        self.db = open_store(path)
        upgraded, = self.db.relationship_events.pending(1, VERIFIER_VERSION)
        self.assertEqual((upgraded.event_id, upgraded.retry_count, upgraded.next_attempt_at),
                         ("old-event", 0, ""))
        self.db.close()
        self.db = open_store(path)
        self.assertEqual(self.db.relationship_events.pending(1, VERIFIER_VERSION)[0], upgraded)

    def test_missing_source_and_malformed_candidate_abstain_without_retry(self) -> None:
        source = self._source("valid", "鱼，谢谢你")
        for event_id, reason, source_id in (
            ("missing", "gratitude", "not-present"),
            ("invalid", "not-a-reason", source.id),
        ):
            self.db.relationship_events.record_pending({
                "event_id": event_id, "verifier_version": VERIFIER_VERSION,
                "subject_id": "u1", "reason": reason, "strength": "strong",
                "scope": "private", "event_at": source.at,
                "primary_source_id": source_id, "source_ids": (source_id,),
            })

        async def provider_for(_session):
            raise AssertionError("invalid evidence must not call the model")

        service = MaintenanceService(
            artifacts=self.db.artifacts, sources=self.db.sources, cache=self.cache,
            journal=SimpleNamespace(span=lambda *_a, **_kw: nullcontext({}), record=lambda *_a, **_kw: None),
            task_id=lambda: "weekly", logger=SimpleNamespace(info=lambda *_a: None, warning=lambda *_a: None),
            clock=lambda: datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc),
            relationship_events=self.db.relationship_events, provider_for=provider_for,
        )
        asyncio.run(service.weekly())
        rows = self.db.relationship_events.by_subject("u1", VERIFIER_VERSION)
        self.assertEqual({row.event_id: (row.status, row.retry_count) for row in rows},
                         {"missing": ("abstain", 0), "invalid": ("abstain", 0)})

    def test_verified_event_commits_readable_versions_and_evidence(self) -> None:
        source = self._source("positive", "鱼，谢谢你帮我解决了问题")
        self._verified(source, RelationshipReason.GRATITUDE)
        first = datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=first,
        ), 1)
        first_snapshot = RelationshipReader(self.cache).get("u1")
        self.assertGreater(first_snapshot.warmth, 0)
        self.assertGreater(first_snapshot.familiarity, 0)
        self.assertEqual(first_snapshot.revision, 1)
        self.assertEqual(RelationshipReader(self.cache).get("other").evidence_count, 0)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=first,
        ), 0)
        later = first + datetime.timedelta(days=45)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=later,
        ), 1)
        self.assertLess(RelationshipReader(self.cache).get("u1").warmth, first_snapshot.warmth)
        self.assertEqual([row["revision"] for row in self.db.artifacts.history(relationship_id("u1"))], [1, 2])
        record = self.db.artifacts.inspect_record(relationship_id("u1"))
        self.assertEqual({row["id"] for row in record["sources"]}, {source.id})
        self.assertTrue(self.db.ledger.verify())

    def test_migration_queues_historical_v1_without_copying_affinity(self) -> None:
        source = self._source("legacy", "鱼，你帮我太多了，谢谢你")
        memory = make(
            "memory", {"text": "对鱼表达感谢", "level": "scene", "about": "relation",
                       "relationship_policy_version": "relationship-v1",
                       "relationship_reason": "gratitude", "relationship_strength": "mild"},
            subject_id="u1", lineage={"sources": (source.id,)},
        )
        self.db.artifacts.commit(memory, expected_revision=0, op="create", source_ids=(source.id,))
        newer = revise(memory, payload={"text": "保留的普通记忆", "level": "scene"})
        self.db.artifacts.commit(newer, expected_revision=1, op="revise", source_ids=(source.id,))
        self.assertEqual(migrate_v1_candidates(self.db.artifacts, self.db.sources, self.db.relationship_events), 1)
        self.assertEqual(migrate_v1_candidates(self.db.artifacts, self.db.sources, self.db.relationship_events), 0)
        event, = self.db.relationship_events.pending(10)
        self.assertEqual(event.origin_revision, 1)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache,
        ), 0)  # Pending evidence cannot affect a relationship.
        self.db.relationship_events.decide(event.event_id, VERIFIER_VERSION, "verified")
        as_of = datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=as_of,
        ), 1)
        relation = self.db.artifacts.get(relationship_id("u1"))
        self.assertEqual(relation.header.lineage.derived_from, (memory.header.id,))
        self.assertEqual([row["revision"] for row in self.db.artifacts.history(memory.header.id)], [1, 2])

    def test_migration_does_not_infer_unzoned_or_missing_source_identity(self) -> None:
        naive = Source("naive", "naive", "bot:FriendMessage:u1", "u1", "user",
                       "鱼，早上好", "2026-10-26T12:00:00")
        self.db.sources.append_sources([naive])
        payload = {"text": "早上问候鱼", "level": "scene", "about": "relation",
                   "relationship_policy_version": "relationship-v1",
                   "relationship_reason": "friendly_greeting", "relationship_strength": "mild"}
        for source_id in (naive.id, "missing"):
            memory = make("memory", payload, subject_id="u1", lineage={"sources": (source_id,)})
            self.db.artifacts.commit(memory, expected_revision=0, op="create")
        self.assertEqual(migrate_v1_candidates(self.db.artifacts, self.db.sources, self.db.relationship_events), 0)
        self.assertEqual(self.db.relationship_events.pending(10), ())
        self.assertEqual(self.db.artifacts.count("memory"), 2)

    def test_v1_relation_and_deactivation_stay_versioned_and_neutral(self) -> None:
        source = self._source("v1", "鱼，你真蠢")
        legacy = make(
            "relationship", {"summary": "关系状态：冷淡", "affinity": -0.7,
                             "confidence": 0.9, "evidence_count": 1, "relation_band": "low",
                             "policy": {"version": "relationship-v1"}},
            id=relationship_id("u1"), subject_id="u1",
            lineage={"sources": (source.id,)},
        )
        self.db.artifacts.commit(legacy, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(legacy)
        self.assertEqual(RelationshipReader(self.cache).get("u1").trust, 0)
        self._verified(source, RelationshipReason.INSULT)
        at = datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=at,
        ), 1)
        self.assertLess(RelationshipReader(self.cache).get("u1").trust, 0)
        self.assertEqual([row["revision"] for row in self.db.artifacts.history(legacy.header.id)], [1, 2])
        deactivated = revise(self.db.artifacts.get(legacy.header.id), state="forgotten")
        self.db.artifacts.commit(deactivated, expected_revision=2, op="forget")
        self.cache.put(deactivated)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache,
            as_of=at + datetime.timedelta(days=1),
        ), 0)
        self.assertEqual(RelationshipReader(self.cache).get("u1").evidence_count, 0)

    def test_weekly_migration_retries_model_failure_then_projects_verified_evidence(self) -> None:
        source = self._source("weekly", "鱼，谢谢你帮我理清这个问题")
        old = make(
            "memory", {"text": "感谢鱼", "level": "scene", "about": "relation",
                       "relationship_policy_version": "relationship-v1",
                       "relationship_reason": "gratitude", "relationship_strength": "mild"},
            subject_id="u1", lineage={"sources": (source.id,)},
        )
        self.db.artifacts.commit(old, expected_revision=0, op="create", source_ids=(source.id,))
        self.cache.put(old)

        class Journal:
            @contextmanager
            def span(self, *_args, **_kwargs):
                yield {}

            def record(self, *_args, **_kwargs):
                pass

        class Provider:
            def __init__(self):
                self.fail = True

            async def text_chat(self, **_kwargs):
                if self.fail:
                    raise RuntimeError("model unavailable")
                return SimpleNamespace(completion_text=json.dumps({
                    "reason": "gratitude", "source_ids": [source.id],
                    "target": "assistant", "decision": "verified",
                }))

        provider = Provider()

        async def provider_for(_session):
            return provider

        moment = [datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)]
        service = MaintenanceService(
            artifacts=self.db.artifacts, sources=self.db.sources, cache=self.cache,
            journal=Journal(), task_id=lambda: "weekly", logger=SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
            clock=lambda: moment[0],
            relationship_events=self.db.relationship_events, provider_for=provider_for,
        )
        self.assertEqual(asyncio.run(service.weekly())["relationships"], 0)
        self.assertEqual(len(self.db.relationship_events.pending(10)), 1)
        self.assertEqual(RelationshipReader(self.cache).get("u1").evidence_count, 0)
        self.assertEqual(self.db.relationship_events.pending(10)[0].retry_count, 1)
        provider.fail = False
        self.assertEqual(asyncio.run(service.weekly())["relationships"], 0)
        moment[0] += datetime.timedelta(minutes=1)
        self.assertEqual(asyncio.run(service.weekly())["relationships"], 1)
        self.assertGreater(RelationshipReader(self.cache).get("u1").warmth, 0)
        self.assertEqual(self.db.relationship_events.pending(10), ())
        self.assertEqual([row["revision"] for row in self.db.artifacts.history(old.header.id)], [1])


    def test_nonstandard_legacy_relation_does_not_create_competing_head(self) -> None:
        source = self._source("legacy-id", "鱼，你真蠢")
        legacy = make(
            "relationship", {"summary": "关系状态：冷淡", "affinity": -0.5,
                             "policy": {"version": "relationship-v1"}},
            id="legacy_relationship_u1", subject_id="u1",
        )
        self.db.artifacts.commit(legacy, expected_revision=0, op="create")
        self.cache.put(legacy)
        self._verified(source, RelationshipReason.INSULT)
        at = datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=at,
        ), 0)
        self.assertIsNone(self.db.artifacts.get(relationship_id("u1")))
        self.assertEqual(RelationshipReader(self.cache).get("u1").evidence_count, 0)

    def test_weekly_repair_links_prior_verified_negative_and_lowers_tension(self) -> None:
        insult = self._source("insult", "鱼，你真蠢")
        self._verified(insult, RelationshipReason.INSULT)
        start = datetime.datetime(2026, 10, 26, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(consolidate_relationships(
            self.db.artifacts, self.db.sources, self.db.relationship_events, self.cache, as_of=start,
        ), 1)
        before = RelationshipReader(self.cache).get("u1")
        apology = Source("apology", "apology", insult.session_id, "u1", "user",
                         "鱼，刚才辱骂你是我的错，对不起。", "2026-10-26T12:05:00+00:00")
        self.db.sources.append_sources([apology])
        prior = self.db.relationship_events.by_subject("u1", VERIFIER_VERSION)[0]
        candidate = RelationshipCandidate("u1", RelationshipReason.REPAIR, RelationshipStrength.MILD,
                                          apology.id, (apology.id,), apology.session_id, ConversationScope.PRIVATE)
        self.db.relationship_events.record_pending({
            "event_id": relationship_event_id(candidate), "verifier_version": VERIFIER_VERSION,
            "subject_id": "u1", "reason": candidate.reason.value, "strength": candidate.strength.value,
            "scope": candidate.scope.value, "event_at": apology.at,
            "primary_source_id": apology.id, "source_ids": candidate.source_ids,
        })

        class Provider:
            async def text_chat(self, **_kwargs):
                return SimpleNamespace(completion_text=json.dumps({
                    "reason": "repair", "source_ids": [apology.id], "target": "assistant",
                    "decision": "verified", "repair_of": prior.event_id,
                }))

        async def provider_for(_session):
            return Provider()

        service = MaintenanceService(
            artifacts=self.db.artifacts, sources=self.db.sources, cache=self.cache,
            journal=SimpleNamespace(span=lambda *_a, **_kw: nullcontext({}), record=lambda *_a, **_kw: None),
            task_id=lambda: "weekly", logger=SimpleNamespace(info=lambda *_: None, warning=lambda *_: None),
            clock=lambda: start + datetime.timedelta(minutes=5),
            relationship_events=self.db.relationship_events, provider_for=provider_for,
        )
        self.assertEqual(asyncio.run(service.weekly())["relationships"], 1)
        after = RelationshipReader(self.cache).get("u1")
        self.assertLess(after.tension, before.tension)
        self.assertEqual(after.revision, 2)
        decided = self.db.relationship_events.by_subject("u1", VERIFIER_VERSION)
        self.assertEqual(next(row for row in decided if row.reason == "repair").repair_of, prior.event_id)

if __name__ == "__main__":
    unittest.main(verbosity=2)
