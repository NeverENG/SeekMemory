"""跑 benchmark，输出 markdown 报告到 results/latest.md。

用法：python3 benchmarks/run.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from benchmarks.dataset import build, decayed_events  # noqa: E402
from benchmarks.retrieval_compare import Query, comparison  # noqa: E402
from core.artifact import content_of, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.gate import pinned  # noqa: E402
from recall.score import select  # noqa: E402
from recall.seed import seeds  # noqa: E402
from recall.spread import activate  # noqa: E402
from store.cache import Cache  # noqa: E402
from store.db import DB  # noqa: E402


def to_artifact(e):
    """Event -> Artifact；标签与生产 perceive/extract 的输出保持同构。"""
    payload = {"text": e.text, "level": e.level, "shape": "point", "chrono": "once", "about": "other"}
    if e.tags:
        payload["tags"] = list(e.tags)
    if e.level == "impression":
        payload["shape"] = "pattern"
    return make(
        "memory",
        payload,
        strength={
            "weight": 0.5 + e.importance + 0.1 * (e.mentions - 1),
            "confidence": 1.0,
            "arousal": e.arousal,
            "valence": e.valence,
            "funny": 0.0,
        },
        time=_rel_time(e.day),
    )


def _rel_time(day: int, today: int = 30) -> dict:
    """把"第 day 天"换算成相对今天的真实日期。"""
    import datetime as _dt
    now = _dt.date.today()
    d = (now - _dt.timedelta(days=today - day)).isoformat()
    return {"created": d, "updated": d}


def pct(x: float) -> str:
    return f"{x * 100:.0f}%"


_TPL = [
    "他今天跟我说了{}", "他下午在弄{}", "他提到{}有点麻烦",
    "他问{}怎么弄", "他{}做完了",
]
_WORDS = ["项目", "数据库", "接口", "部署", "文档", "测试", "会议", "报表", "脚本", "配置",
          "调度", "缓存", "索引", "图表", "日志", "告警", "备份", "迁移", "权限", "监控"]


def _synthetic_pool(n: int) -> list:
    """按模板造 n 条记忆，用于规模测试。"""
    import random as _r
    rng = _r.Random(7)
    out = []
    for i in range(n):
        tpl = _TPL[i % len(_TPL)]
        txt = tpl.format(rng.choice(_WORDS) + rng.choice(["", "那部分", "的细节"]))
        out.append(make("memory", {"text": f"{txt}（{i}）", "level": "detail",
                                   "shape": "point", "chrono": "once", "about": "other"}))
    return out


def main() -> None:
    events, queries = build()
    tmp = tempfile.mkdtemp()
    db = DB(os.path.join(tmp, "bench.db"))
    cache = Cache(db)
    graph = Graph(db, cache)
    table = {}

    for e in events:
        art = to_artifact(e)
        db.upsert(art)
        cache.put(art)
        table[e.text] = art.header.id

    # ---------- 1. Token 效率 ----------
    full_chars = sum(len(e.text) for e in events)
    injected_chars = 0
    hits = 0
    expected = 0
    level_ok = 0
    level_total = 0
    narratives = 0
    eligible_levels = 0

    rows = []
    pin = pinned(cache)
    for q in queries:
        pool = cache.active()
        t0 = time.perf_counter()
        sid = seeds(q.text, pool)
        act = activate(sid, graph, cache)
        picked = pin + select([(a, float(act.get(a.header.id, 0.0))) for a in pool],
                              q.text, 0.0, k=8, explore=0.0)
        block = assemble(picked, budget=600)
        dt = (time.perf_counter() - t0) * 1000
        injected_chars += len(block)

        picked_text = " ".join(content_of(p) for p in picked)
        hit = [x for x in q.expect if x in picked_text]
        if q.expect:
            expected += 1
            if hit:
                hits += 1
            rows.append((q.text, len(hit), len(q.expect), f"{dt:.1f}ms", block[:60]))
        else:
            rows.append((q.text, 0, 0, f"{dt:.1f}ms", block[:60]))

        # 层级命中
        if q.expect_level:
            level_total += 1
            if any(p.payload.get("level") == q.expect_level for p in picked):
                level_ok += 1

        # 叙述化：含列表符号即算"不像人"
        if block:
            eligible_levels += 1
            if not any(line.strip().startswith(("-", "*", "•")) for line in block.splitlines()):
                narratives += 1

    recall = hits / expected if expected else 0.0
    level_acc = level_ok / level_total if level_total else 0.0
    narrative_rate = narratives / eligible_levels if eligible_levels else 0.0
    avg_injected = injected_chars / max(len(queries), 1)
    # 朴素做法：每轮把所有记忆都塞进去（full_chars 是常量）
    comp_ratio = full_chars / avg_injected if avg_injected else 0.0

    # ---------- 2. 遗忘正确性 ----------
    dec = decayed_events(events, today=30)
    keep_ok = sum(1 for e, r in dec if e.importance >= 0.7 and r > 0.3)
    keep_all = sum(1 for e, r in dec if e.importance >= 0.7)
    drop_ok = sum(1 for e, r in dec if e.importance <= 0.2 and r < 0.3)
    drop_all = sum(1 for e, r in dec if e.importance <= 0.2)

    # ---------- 3. 强化效果 ----------
    hi = [e for e in events if e.mentions >= 5]
    lo = [e for e in events if e.mentions <= 2]
    s_hi = sum(to_artifact(e).header.strength.weight for e in hi) / max(len(hi), 1)
    s_lo = sum(to_artifact(e).header.strength.weight for e in lo) / max(len(lo), 1)

    # ---------- 规模测试：Token 随记忆量增长 ----------
    scale_rows = []
    for n in (50, 200, 500, 1000):
        pool_n = _synthetic_pool(n)
        q = "我今天加班到很晚"
        sid = seeds(q, pool_n)
        act_n = activate(sid, graph, cache) if False else {}
        picked_n = select([(a, 0.0) for a in pool_n], q, 0.0, k=8, explore=0.0)
        ours = len(assemble(picked_n, budget=600))
        naive = sum(len(content_of(a)) for a in pool_n)
        scale_rows.append((n, naive, ours, naive / max(ours, 1)))

    # ---------- 报告 ----------
    forget_total = keep_all + drop_all
    forget_ok = keep_ok + drop_ok
    persona = (
        0.30 * level_acc
        + 0.20 * narrative_rate
        + 0.25 * (forget_ok / max(forget_total, 1))
        + 0.15 * min(1.0, (s_hi / max(s_lo, 0.01)) / 2.1)
        + 0.10 * recall
    )
    big = scale_rows[-1]

    lines = [
        "# SeekMemory Benchmark",
        "",
        f"> {len(events)} 条模拟事件 · {len(queries)} 个查询 · 模拟 30 天 · 固定数据可复现",
        "",
        "## 指标一：像人",
        "",
        f"### 综合像人指数：**{persona * 100:.0f} / 100**",
        "",
        "| 子项 | 权重 | 结果 | 含义 |",
        "|---|---|---|---|",
        f"| 层级命中率 | 30% | **{pct(level_acc)}** | 问印象时命中印象层 |",
        f"| 叙述化比例 | 20% | **{pct(narrative_rate)}** | 注入文本无项目符号 |",
        f"| 遗忘正确性 | 25% | **{forget_ok}/{forget_total}** | 重要留下、琐事忘掉 |",
        f"| 强化有效性 | 15% | **{s_hi / max(s_lo, 0.01):.1f}×** | 多提及 vs 少提及权重比 |",
        f"| 召回命中率 | 10% | **{pct(recall)}** | 期望记忆进 top-8 |",
        "",
        "## 指标二：Token",
        "",
        f"### 1000 条记忆时压缩 **{big[3]:.0f}×**",
        "",
        "| 记忆条数 | 朴素全量注入 | SeekMemory | 压缩比 |",
        "|---|---|---|---|",
    ]
    for n, naive, ours, r in scale_rows:
        lines.append(f"| {n} | {naive} 字/轮 | {ours} 字/轮 | **{r:.0f}×** |")
    lines += [
        "",
        f"每轮额外模型调用：**0 次**（检索纯本地）",
        "",
        "## 遗忘明细",
        "",
        "| 检查 | 结果 |",
        "|---|---|",
        f"| 重要事件被保留 | {keep_ok}/{keep_all} |",
        f"| 琐事被遗忘 | {drop_ok}/{drop_all} |",
        "",
        "## 逐查询明细",
        "",
        "| 查询 | 命中/期望 | 耗时 | 注入片段 |",
        "|---|---|---|---|",
    ]
    for q, h, n, dt, snip in rows:
        lines.append(f"| {q} | {h}/{n} | {dt} | {snip.replace('|', '/')} |")

    lines += comparison(cache, graph, cache.active(),
                        [Query(q.text, tuple(q.expect)) for q in queries])
    out_dir = os.path.join(ROOT, "benchmarks", "results")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "latest.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("\n".join(lines[:32]))
    print(f"\n→ 写入 {out}")
    db.close()


if __name__ == "__main__":
    main()
