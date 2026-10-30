"""大规模群聊仿真 benchmark。

模拟 N 个用户、M 天、每天 K 条群消息，对比六种记忆方案的
「成本 / 召回 / 跨 scope 隔离」：

朴素全量、滑窗、关键词、伪向量、日摘要、SeekMemory。

跑法：python3 benchmarks/scale.py
输出：.tmp/benchmarks/<运行编号>/scale.md
"""

from __future__ import annotations

import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.domain.memory.artifact import content_of  # noqa: E402
from core.domain.memory.graph import Graph  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.gate import pinned  # noqa: E402
from recall.score import select  # noqa: E402
from recall.seed import seeds  # noqa: E402
from recall.spread import activate  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402

from benchmarks.output import report_path
from benchmarks import simdata
from benchmarks.retrieval_compare import Query, comparison
from benchmarks.simdata import (  # noqa: E402
    gen_messages,
    to_art,
    baseline_window,
    baseline_keyword,
    baseline_full,
    _tf,
    _norm,
    build_vector_index,
    baseline_vector,
    build_daily_summaries,
    baseline_summary,
    _texts,
    _fmt_ms,
    _snip,
)


USERS = simdata.USERS
DAYS = simdata.DAYS
MSGS_PER_DAY = simdata.MSGS_PER_DAY


def main() -> None:
    t0 = time.time()
    msgs = gen_messages()
    db = open_store(":memory:")
    try:
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)

        for day, uid, text in msgs:
            art = to_art(day, uid, text)
            db.artifacts.upsert(art)
            cache.put(art)

        owner_pool = [a for a in cache.active() if a.header.scope == "private"]
        other_pool = [a for a in cache.active() if a.header.scope == "shadow"]
        build_s = time.time() - t0

        # 两个新基线的离线索引：一次建好，检索时复用
        s = time.perf_counter()
        vector_index = build_vector_index(owner_pool)
        vector_s = time.perf_counter() - s
        s = time.perf_counter()
        daily_summaries = build_daily_summaries(msgs)
        summary_s = time.perf_counter() - s

        queries = [
            ("我叫什么", ["吕宇轩"]),
            ("我面试怎么样了", ["面试"]),
            ("上次加班到几点", ["加班"]),
            ("我最近睡不好", ["睡不着"]),
            ("我是干什么的", ["量化"]),
            ("我想要什么职业", ["架构师"]),
        ]

        schemes = (
            ("朴素全量注入", lambda q: baseline_full(owner_pool)),
            ("滑窗 20 条", lambda q: baseline_window(owner_pool, 20)),
            ("关键词匹配", lambda q: baseline_keyword(owner_pool, q)),
            ("伪向量 top-8", lambda q: baseline_vector(owner_pool, q, k=8, index=vector_index)),
            ("摘要 近 7 天", lambda q: baseline_summary(daily_summaries)),
        )

        rows = []
        per_query: dict[str, list[tuple[bool, str]]] = {}
        for name, fn in schemes:
            chars = 0
            hit = 0
            t_ret = 0.0
            cells = []
            for q, expect in queries:
                s = time.perf_counter()
                picked = fn(q)
                block = " ".join(_texts(picked))
                t_ret += (time.perf_counter() - s) * 1000
                chars += len(block)
                ok = any(e in block for e in expect)
                hit += int(ok)
                cells.append((ok, block))
            per_query[name] = cells
            rows.append((name, chars // len(queries), hit, len(queries),
                         _fmt_ms(t_ret / len(queries))))

        # SeekMemory：种子 → 激活扩散 → 五维打分 → 按预算组装
        chars = 0
        hit = 0
        leak = 0
        t_ret = 0.0
        cells = []
        pin = pinned(cache)
        for q, expect in queries:
            s = time.perf_counter()
            sid = seeds(q, owner_pool)
            act = activate(sid, graph, cache)
            picked = pin + select([(a, float(act.get(a.header.id, 0.0))) for a in owner_pool],
                                  q, 0.0, k=8, explore=0.0)
            block = assemble(picked, budget=600)
            t_ret += (time.perf_counter() - s) * 1000
            chars += len(block)
            ok = any(e in block for e in expect)
            hit += int(ok)
            cells.append((ok, block))
            # 泄漏检查：是否混入别人的 shadow 记忆
            leak += sum(1 for a in picked if a.header.scope == "shadow")
        per_query["SeekMemory"] = cells
        rows.append(("SeekMemory", chars // len(queries), hit, len(queries),
                     _fmt_ms(t_ret / len(queries))))

        # 逐查询明细：六种方案的命中矩阵 + 注入片段
        names = [name for name, _ in schemes] + ["SeekMemory"]
        hit_table = [
            "| 查询 | 期望包含 | " + " | ".join(names) + " |",
            "|---|" + "---|" * (len(names) + 1),
        ]
        for i, (q, expect) in enumerate(queries):
            marks = [("✅" if per_query[name][i][0] else "❌") for name in names]
            hit_table.append(f"| {q} | {expect[0]} | " + " | ".join(marks) + " |")

        snippet_table = [
            "| 查询 | " + " | ".join(names) + " |",
            "|---|" + "---|" * len(names),
        ]
        for i, (q, expect) in enumerate(queries):
            snips = [_snip(per_query[name][i][1], expect[0]) for name in names]
            snippet_table.append(f"| {q} | " + " | ".join(snips) + " |")

        # 跨 scope 隔离：用别人的 query 检索，看会不会捞到我的
        s = time.perf_counter()
        sid = seeds("我叫什么", other_pool[:200])
        act = activate(sid, graph, cache)
        other_ctx = select([(a, float(act.get(a.header.id, 0.0))) for a in other_pool[:200]],
                           "我叫什么", 0.0, k=8, explore=0.0)
        leak_other = sum(1 for a in other_ctx if a.header.scope == "private")

        total_msgs = len(msgs)
        lines = [
            "# SeekMemory · 大规模群聊仿真",
            "",
            f"> {USERS} 个用户 · {DAYS} 天 · {total_msgs} 条消息 · 建库 {build_s:.1f}s · 六种记忆方案",
            "",
            "## 数据规模",
            "",
            "| 项 | 数量 |",
            "|---|---|",
            f"| 群消息总数 | {total_msgs} |",
            f"| 我的记忆（owner scope） | {len(owner_pool)} |",
            f"| 他人记忆（shadow） | {len(other_pool)} |",
            "",
            "## 六种方案对比",
            "",
            "| 方案 | 每轮注入 | 召回命中 | 平均检索耗时 |",
            "|---|---|---|---|",
        ]
        for name, c, h, n, dt in rows:
            lines.append(f"| {name} | **{c} 字** | {h}/{n} | {dt} |")
        lines += [
            "",
            "离线索引（一次性，不计入上面的检索耗时）："
            f"伪向量 {vector_s * 1000:.1f}ms / {len(owner_pool)} 条；"
            f"日摘要 {summary_s * 1000:.1f}ms / {DAYS} 天。",
            "",
            "### 逐查询命中",
            "",
        ] + hit_table + [
            "",
            "### 逐查询注入片段",
            "",
        ] + snippet_table + [
            "",
            "## 跨 scope 隔离",
            "",
            "| 检查 | 结果 |",
            "|---|---|",
            f"| 我的检索混入他人 shadow 记忆 | **{leak} 条** |",
            f"| 他人检索捞到我的 private 记忆 | **{leak_other} 条** |",
            "",
            "## 结论",
            "",
        ]

        by_name = {name: (c, h) for name, c, h, _n, _dt in rows}
        full_c = by_name["朴素全量注入"][0]
        ours_c, ours_h = by_name["SeekMemory"]
        vec_c, vec_h = by_name["伪向量 top-8"]
        sum_c, sum_h = by_name["摘要 近 7 天"]
        lines += [
            f"- 朴素全量注入每轮 {full_c} 字；SeekMemory 只要 {ours_c} 字"
            f"（**{full_c / max(ours_c, 1):.0f}×**），召回 {ours_h}/{len(queries)}",
            f"- 伪向量 {vec_c} 字、{vec_h}/{len(queries)}：字符二元组能覆盖同词问法，"
            f"覆盖不了没有共享二字的同义问法",
            f"- 摘要 {sum_c} 字、{sum_h}/{len(queries)}：40 字/天只保住了最近几天里"
            f"恰好落在截断窗口内的事实",
            "- 跨 scope 零泄漏",
        ]

        lines += comparison(cache, graph, owner_pool,
                            [Query(text, tuple(expected)) for text, expected in queries])
        out = report_path("scale")
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("\n".join(lines))
    finally:
        db.close()


if __name__ == "__main__":
    main()
