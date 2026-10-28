"""端到端冒烟测试：不依赖 AstrBot，验证 core/store/recall 能串起来。"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.artifact import Artifact, content_of, make, validate
from core.graph import Graph
from core.strength import reinforce, retention
from recall.assemble import build as assemble
from recall.score import score, select
from recall.retriever import HybridRetriever
from recall.seed import seeds
from recall.spread import activate
from store.cache import Cache
from store import open_store
from store.ledger import Ledger
from services import TreeService


def _mk(level: str, text: str, parent: str | None = None, weight: float = 1.0) -> Artifact:
    art = make(
        "memory",
        {
            "text": text,
            "level": level,
            "shape": "point",
            "chrono": "once",
            "about": "other",
        },
        strength={"weight": weight, "confidence": 1.0, "arousal": 0.5, "valence": 0.0, "funny": 0.2},
    )
    return art


def main() -> None:
    tmpdir = tempfile.mkdtemp()
    db = open_store(os.path.join(tmpdir, "t.db"))
    cache = Cache(db.artifacts)
    tree = TreeService(db.artifacts, cache)
    graph = Graph(db.artifacts)
    ledger = Ledger(db.ledger)

    impression = _mk("impression", "他有点倔，嘴上不饶人但真有事会帮")
    scene = _mk("scene", "他加班到两点，我说陪他躺会儿")
    detail = _mk("detail", "他说今天被领导骂了")
    media = make(
        "media",
        {"type": "video", "title": "大肥鱼是怎么来的", "url": "https://x", "summary": "讲大肥鱼由来的视频"},
    )

    for art in (impression, scene, detail, media):
        db.artifacts.upsert(art)
        cache.put(art)

    tree.add_under(scene, impression.header.id)
    tree.add_under(detail, scene.header.id)
    graph.link(scene.header.id, detail.header.id, "causal", 0.8)
    ledger.append("create", impression.header.id, None, "h1", "初版")

    assert cache.size() == 4, cache.size()
    assert db.artifacts.get(impression.header.id) is not None
    assert db.artifacts.count() >= 4

    pool = cache.active()
    seed_ids = seeds("我今天加班到很晚，好累", pool)
    assert seed_ids, "种子为空"
    activation = activate(seed_ids, graph, cache)
    assert activation, "激活为空"

    cands = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
    picked = select(cands, "我今天加班到很晚，好累", 0.0, k=3, explore=0.0)
    assert picked, "未选中任何记忆"

    block = assemble(picked, budget=600)
    assert block.strip(), "组装为空"
    lexical = HybridRetriever(graph, cache).retrieve("加班", cache.active())
    assert any(candidate.lexical > 0 for candidate in lexical), "BM25 未提供词面证据"
    print("--- 注入块 ---")
    print(block)

    assert ledger.verify() is True
    weaker = reinforce(impression.header.strength, "spoken")
    assert weaker.weight > impression.header.strength.weight
    assert 0 < retention(detail.header.strength, "point", 3) < 1

    print("\nOK 全部通过")
    db.close()


if __name__ == "__main__":
    main()
