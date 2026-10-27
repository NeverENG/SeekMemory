"""Host-port conformance layer — docs/HOST-PORTS.md v1.

The cases below target the **ports**, not AstrBot event objects: any host
implementation must pass them, and the existing AstrBot adapter passes them
without this file being modified.

Run: python scripts/run_tests.py --layer conformance
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 临时库落在仓库内：系统临时目录在受限沙箱里不可写。
# 另外刻意不用 tempfile.mkdtemp —— 它在 Windows 上建出的目录 sqlite 打不开
# （os.access 报可写，但 sqlite3.connect 返回 "unable to open database file"），
# 换成 os.makedirs 建目录。
TMP_ROOT = os.path.join(ROOT, ".tmp", "conformance")

from app.contracts import ChatResponse, DialogueTurn  # noqa: E402
from core.artifact import Lineage, make  # noqa: E402
from core.disclosure import DisclosureLevel, RecallScene, decide  # noqa: E402
from core.graph import Graph  # noqa: E402
from core.source import Source  # noqa: E402
from core.versioning import VersionError  # noqa: E402
from recall.pipeline import build_block  # noqa: E402
from store import open_store  # noqa: E402
from store.cache import Cache  # noqa: E402
from tests.absorb_support import absorb  # noqa: E402

FACT = "the user is preparing a job interview"

EXTRACTED = json.dumps(
    [
        {
            "level": "fact",
            "text": FACT,
            "tags": "job interview",
            "about": "other",
            "subject_id": "u1",
            "arousal": 0.4,
            "valence": 0.2,
            "funny": 0.0,
        }
    ]
)


class CountingModel:
    """A ChatModel that counts calls, so "0 calls" is observable, not assumed."""

    def __init__(self, text: str = EXTRACTED, fail: bool = False) -> None:
        self.text = text
        self.fail = fail
        self.calls = 0

    async def complete(self, request):  # noqa: ANN001, ANN201 - port shape
        self.calls += 1
        if self.fail:
            raise RuntimeError("provider unavailable")
        return ChatResponse(text=self.text, model="fake", provider_id="fake")


class HostPortConformanceTest(unittest.TestCase):
    """One test per clause of HOST-PORTS.md."""

    def setUp(self) -> None:
        os.makedirs(TMP_ROOT, exist_ok=True)
        case_dir = os.path.join(TMP_ROOT, f"case_{uuid.uuid4().hex[:8]}")
        os.makedirs(case_dir, exist_ok=True)
        self.addCleanup(shutil.rmtree, case_dir, True)
        self.db = open_store(os.path.join(case_dir, "t.db"))
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.config = {"bm25_enabled": False, "explore_rate": 0.0, "budget_chars": 600}

    # ---------- helpers ----------
    def add_source(self, sid: str = "s1", *, umo: str = "umo1", subject: str = "u1",
                   text: str = "raw text", role: str = "user") -> Source:
        src = Source(sid, "turn1", umo, subject, role, text, "2026-10-27T10:00:00")
        self.db.sources.append_sources([src])
        return src

    def add_artifact(self, family: str, payload: dict, *, scope: str = "private",
                     subject: str = "u1", said_by: str = "u1",
                     source_id: str = "s1"):  # noqa: ANN201
        art = make(
            family,
            payload,
            scope=scope,
            subject_id=subject,
            said_by=said_by,
            lineage=Lineage(sources=(source_id,)),
        )
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source_id,))
        self.cache.put(art)
        return art

    def recall(self, *, umo: str = "umo1", text: str = "hello", speaker: str = "u1",
               private: bool = True):
        return build_block(
            self.cache,
            self.graph,
            self.db.artifacts,
            self.db.sources,
            umo,
            text,
            private,
            self.config.get,
            "bot:FriendMessage:p1",
            speaker,
            dry_run=True,
        )

    # ---------- 1. capture → recall round trip ----------
    def test_capture_then_recall_returns_the_fact(self) -> None:
        self.add_source(text="I have an interview tomorrow")
        outcome = asyncio.run(
            absorb(
                [DialogueTurn("umo1", "u1", "user", "I have an interview tomorrow", "", "s1")],
                self.db.artifacts,
                self.db.sources,
                self.cache,
                self.graph,
                CountingModel(),
            )
        )
        self.assertGreaterEqual(outcome.written, 1, "抽取应当写入至少一条 Artifact")
        block, _info = self.recall(text="job interview")
        self.assertIn(FACT, block, "刚捕获的事实应当能从召回路径取回")

    # ---------- 2. secret never injected ----------
    def test_secret_family_is_never_injected(self) -> None:
        self.add_source()
        self.add_artifact("secret", {"shadow_text": "shadow phrase"}, scope="private")
        block, _info = self.recall()
        self.assertNotIn("shadow phrase", block, "secret 记录不得进入常规注入块")

    # ---------- 3. cross-subject isolation ----------
    def test_recall_does_not_cross_subjects(self) -> None:
        self.add_source()
        self.add_artifact("memory", {"text": "only for u1", "level": "fact"}, subject="u1")
        block, _info = self.recall(speaker="u2")
        self.assertNotIn("only for u1", block, "他人私有记忆不得出现在本主体上下文")

    # ---------- 4. duplicate source id is idempotent ----------
    def test_duplicate_source_id_is_idempotent(self) -> None:
        src = Source("s_dup", "turn1", "umo1", "u1", "user", "same message", "t1")
        self.assertEqual(self.db.sources.append_sources([src]), 1)
        self.assertEqual(self.db.sources.append_sources([src]), 0, "重复 id 不得重复计数")
        self.assertEqual(len(self.db.sources.sources_by_ids(["s_dup"])), 1)

    # ---------- 5. stale expected_revision is rejected ----------
    def test_commit_rejects_stale_expected_revision(self) -> None:
        self.add_source()
        art = make(
            "memory",
            {"text": "v1", "level": "fact"},
            scope="private",
            subject_id="u1",
            said_by="u1",
            lineage=Lineage(sources=("s1",)),
        )
        self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))
        with self.assertRaises(VersionError, msg="陈旧 revision 必须抛错而不是覆盖"):
            self.db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("s1",))

    # ---------- 6. recall performs no model calls ----------
    def test_recall_makes_no_model_calls(self) -> None:
        self.add_source()
        self.add_artifact("memory", {"text": "some memory", "level": "fact"})
        before = len(self.db.ledger.entries())
        self.recall(text="some memory")
        self.assertEqual(len(self.db.ledger.entries()), before, "召回期间不得产生模型调用记账")

    # ---------- 7. model failure keeps the input recoverable ----------
    def test_model_failure_keeps_pending_input(self) -> None:
        self.add_source(text="I have an interview tomorrow")
        outcome = asyncio.run(
            absorb(
                [DialogueTurn("umo1", "u1", "user", "I have an interview tomorrow", "", "s1")],
                self.db.artifacts,
                self.db.sources,
                self.cache,
                self.graph,
                CountingModel(fail=True),
            )
        )
        self.assertTrue(outcome.model_failed, "模型失败必须可观测")
        self.assertEqual(self.db.artifacts.list("memory"), [], "模型失败不得写入半成品 Artifact")

    # ---------- 8. low affinity degrades disclosure ----------
    def test_low_affinity_degrades_disclosure(self) -> None:
        self.add_source(umo="other")
        art = self.add_artifact(
            "memory",
            {"text": "unrelated detail", "level": "fact"},
            scope="shared",
            subject="u1",
        )
        scene = RecallScene("umo1", "u1", "u1", ("u1",))
        decision = decide(art, scene, 0.0, origin_sessions=("other",))
        self.assertNotEqual(
            decision.level,
            DisclosureLevel.FULL,
            "上下文亲和度低时不得全文披露",
        )

    # ---------- 9. injection respects the character budget ----------
    def test_injection_respects_budget(self) -> None:
        self.add_source()
        for i in range(5):
            self.add_artifact(
                "memory",
                {"text": f"long memory {i} " + "x" * 60, "level": "fact"},
            )
        self.config["budget_chars"] = 60
        block, info = self.recall()
        self.assertLessEqual(
            len(block),
            60 * 2,
            f"注入块超出预算：{len(block)} 字符（info={info.get('chars')}）",
        )


if __name__ == "__main__":
    unittest.main()
