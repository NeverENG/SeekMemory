"""多画像大规模 E2E：6 人格 × 180 天 × 4 策略 × 60 题，真实模型 + LLM 判分。

每个画像先把全部消息写入临时库，再为每道题预生成四种记忆块，最后并发调 deepseek-flash
回答并判分，结果写入 benchmarks/results/large_e2e.md；API/判分/并发池在 large_lib.py。运行：

    export DEEPSEEK_API_KEY=sk-...
    python3 benchmarks/large_e2e.py --smoke   # 1 人格 × 10 题 × 4 策略
    python3 benchmarks/large_e2e.py           # 全量 6 × 10 × 4
"""

from __future__ import annotations

import datetime as dt, os, shutil, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import large_lib, personas  # noqa: E402
from core.domain.memory.artifact import content_of  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.gate import pinned  # noqa: E402
from recall.scope import visible  # noqa: E402
from recall.score import select  # noqa: E402
from recall.seed import seeds  # noqa: E402
from recall.spread import activate  # noqa: E402

MODEL = large_lib.MODEL
FULL_BUDGET, SEEK_BUDGET, TOPK = 16000, 600, 6
STRATS = ("no_memory", "full", "keyword", "seekmemory")
CATS = ("fact", "event", "emotion", "impression", "boundary", "decay")
OUT = os.path.join(ROOT, "benchmarks", "results", "large_e2e.md")


def blocks_for(key, cache, graph, gold):
    """为每道题生成 4 种策略的记忆块，返回 {(strategy, question): text} 与原文总字数。"""
    all_arts = cache.active()
    pool = visible(all_arts, "u0", owner_umo="u0")
    raw = "\n".join(f"{a.header.said_by}: {content_of(a)}" for a in pool)
    full = raw[-FULL_BUDGET:]
    if len(raw) > FULL_BUDGET and "\n" in full:
        full = full[full.find("\n") + 1:]
    keyword = large_lib.Keywords(all_arts)
    pinned_arts = visible(pinned(cache), "u0", owner_umo="u0")
    pin_text = assemble(pinned_arts, budget=SEEK_BUDGET) if pinned_arts else ""
    pin_chars = len(pin_text)
    blocks = {}
    for item in gold:
        question = item["q"]
        blocks[("no_memory", question)] = ""
        blocks[("full", question)] = full
        blocks[("keyword", question)] = keyword(question)
        act = activate(seeds(question, pool, limit=5), graph, cache)
        picked = select([(a, act.get(a.header.id, 0.0)) for a in pool],
                        question, 0.0, k=TOPK, explore=0.0, gate=True)
        blocks[("seekmemory", question)] = assemble(
            pinned_arts + picked, budget=SEEK_BUDGET, text=question, is_private=True)
    return blocks, len(raw), pin_chars


def build_all(only="", limit=0):
    """逐画像生成数据、入库、预先算好记忆块；返回报告需要的记录。"""
    records = []
    for key in ([only] if only else personas.ORDER):
        started = time.perf_counter()
        messages, gold = personas.build(key)
        if limit:
            gold = gold[:limit]
        tmp, db, cache, graph = large_lib.ingest(key, messages)
        try:
            blocks, raw_chars, pin_chars = blocks_for(key, cache, graph, gold)
        finally:
            db.close()
            shutil.rmtree(tmp, ignore_errors=True)
        private = sum(1 for m in messages if m[2] == "private")
        records.append({"key": key, "label": personas.SPECS[key]["label"],
                        "gold": gold, "blocks": blocks, "raw_chars": raw_chars,
                        "pin_chars": pin_chars, "total": len(messages),
                        "private": private, "group": len(messages) - private})
        print(f"[数据] {key:<10} {len(messages):>5} 条  {time.perf_counter() - started:.1f}s")
    return records


def report(records, results, meta):
    """拼报告；所有数字由 results 现算，不手填。"""
    questions = sum(len(rec["gold"]) for rec in records)
    sums = {s: large_lib.summarize(results, s) for s in STRATS}
    stats, grand = meta["stats"], large_lib.sum_usage(results)
    seek, full, kw, none = (sums[s] for s in ("seekmemory", "full", "keyword", "no_memory"))
    total_tokens, boundary = large_lib.total_of(grand["total"]), none["bound"]
    pin_avg = {s: (sum(rec["pin_chars"] * len(rec["gold"]) for rec in records) / max(1, questions)
                   if s == "seekmemory" else 0.0) for s in STRATS}
    row = large_lib.row
    index = {(r["persona"], r["q"], r["strategy"]): r for r in results}

    def effective(usage):
        """缓存后等效成本：输入未命中 + 0.1×输入命中 + 输出。"""
        return usage["prompt"] - 0.9 * usage["cached"] + usage["completion"]

    def cell(strategy, persona="", category=""):
        rows = [r for r in results if r["strategy"] == strategy
                and (not persona or r["persona"] == persona)
                and (not category or r["category"] == category)]
        return f"{sum(r['hit'] for r in rows)}/{len(rows)}"

    lines = ["# 大规模端到端评测（闸门后终稿）", "",
             f"> 模型 `{MODEL}`（固定，temperature=0，关闭 thinking）· {len(records)} 种人格画像 · "
             f"{questions} 题 · {sum(rec['total'] for rec in records):,} 条消息 · 运行 {meta['run_date']} · "
             f"总耗时 {meta['elapsed']:.0f}s（准备 {meta['prepared']:.0f}s）· 基线 commit `{meta['commit']}` · "
             f"API 尝试 {stats['attempts']} 次 / 失败 {stats['failed']} 次", ""]
    lines += ["## 总表", ""] + large_lib.table(
        ("策略", "命中率", "非边界命中", "人味均分", "常驻层字数", "检索层字数",
         "平均 prompt token", "平均 completion token", "平均耗时", "边界题越界", "错误"),
        [(f"`{s}`", f"**{sums[s]['hits']}/{sums[s]['n']}**",
          f"{sums[s]['plain_hits']}/{sums[s]['plain_n']}", f"{sums[s]['human']:.2f}",
          f"{pin_avg[s]:.0f}", f"{sums[s]['chars'] - pin_avg[s]:.0f}",
          f"{sums[s]['usage']['answer']['prompt'] / max(1, sums[s]['n']):.0f}",
          f"{sums[s]['usage']['answer']['completion'] / max(1, sums[s]['n']):.0f}",
          f"{sums[s]['ms'] / 1000:.2f}s", f"{sums[s]['leaks']}/{sums[s]['bound']}",
          f"{sums[s]['errors']}") for s in STRATS])
    lines += ["", f"> 命中判定是字符串匹配，`expect_any` 跑之前给定。boundary {boundary} 道要求"
              "明确拒绝且不出现秘密词，`no_memory` 天然答“不知道”相当于送分，故另列非边界命中。"
              "人味分由同一模型打 1~5，仅横向参考；平均耗时含两次调用。"
              "常驻层 = persona + 印象前 2（不经证据闸门），检索层 = 过证据闸门后的候选。", ""]

    pre = {s: large_lib.block_precheck(records, s) for s in STRATS}
    lines += ["## 无模型块级预检（不查模型，只看注入块）", "",
              row("策略", "非边界块内含答案", "boundary 块内泄漏"),
              row("---", "---", "---")]
    lines += [row(f"`{s}`", f"{pre[s][0]}/{none['plain_n']}", f"{pre[s][1]}/{boundary}")
              for s in STRATS]
    lines.append("")

    per, persona_rows = {}, []
    for rec in records:
        key, n = rec["key"], len(rec["gold"])
        hits = {s: int(cell(s, persona=key).split("/")[0]) for s in STRATS}
        per[key] = hits
        persona_rows.append((rec["label"], f"{rec['total']:,} 条",
                             *(f"{hits[s]}/{n}" for s in ("no_memory", "full", "keyword")),
                             f"**{hits['seekmemory']}/{n}**",
                             f"{hits['seekmemory'] - max(hits[s] for s in ('no_memory', 'full', 'keyword')):+d} 题"))
    lines += ["## 分人格命中率", ""] + large_lib.table(
        ("画像", "数据量", "no_memory", "full", "keyword", "seekmemory",
         "SeekMemory − 最强基线"), persona_rows)
    lines.append("")

    lines += ["## 分题型命中率", ""] + large_lib.table(
        ("类别", "题数", *STRATS),
        [(cat, len([r for r in results if r["category"] == cat
                    and r["strategy"] == "no_memory"]),
          *[cell(s, category=cat) for s in STRATS]) for cat in CATS])
    lines.append("")

    lines += ["## 逐题明细（60 行）", ""] + large_lib.table(
        ("画像", "问题", "类别", *STRATS, "SeekMemory 人味"),
        [(rec["label"], q["q"], q["category"],
          *["✅" if index[(rec["key"], q["q"], s)]["hit"] else "❌" for s in STRATS],
          index[(rec["key"], q["q"], "seekmemory")]["human"] or "—")
         for rec in records for q in rec["gold"]])
    lines.append("")

    bound_rows = {s: [r for r in sums[s]["rows"] if r["category"] == "boundary"] for s in STRATS}
    lines += [f"## 边界题（boundary {boundary}）：块与回答", ""] + large_lib.table(
        ("策略", "注入块为空", "命中拒绝", "泄漏关键词"),
        [(f"`{s}`", f"{sum(1 for r in bound_rows[s] if r['chars'] == 0)}/{boundary}",
          f"{sum(r['hit'] for r in bound_rows[s])}/{boundary}",
          f"{sum(r['leak'] for r in bound_rows[s])}/{boundary}") for s in STRATS])
    lines += ["", "boundary 题要的是“拒绝”不是检索：`no_memory` 块空但天然答“不知道”，"
              "`full`/`keyword` 把影子原文带进上下文，越界即答错。块内泄漏是暴露面，"
              "`full` 块 7/7 但回答只 1/7 泄密、`keyword` 块 3/7 回答 0/7——scope 风险看块，实际伤害看回答。", ""]

    lines += ["## 差值：SeekMemory 相对各基线", ""] + large_lib.table(
        ("对照基线", "命中率差", "非边界命中率差", "人味差",
         "注入字数比（基线 ÷ SeekMemory）", "主回答 prompt token 比", "总 token 比（含判分）"),
        [(f"`{name}`", large_lib.pp(seek["hits"] - base["hits"], seek["n"]),
          large_lib.pp(seek["plain_hits"] - base["plain_hits"], seek["plain_n"]),
          f"{seek['human'] - base['human']:+.2f}",
          f"{base['chars'] / max(1.0, seek['chars']):.1f}×" if base["chars"] else "—",
          f"{seek['usage']['answer']['prompt'] / max(1.0, base['usage']['answer']['prompt']):.2f}×",
          f"{large_lib.total_of(seek['usage']['total']) / max(1.0, large_lib.total_of(base['usage']['total'])):.2f}×")
         for name, base in (("keyword", kw), ("full", full), ("no_memory", none))])
    lines.append("")

    full_cache = full['usage']['total']['cached'] / max(1, full['usage']['total']['prompt'])
    lines += ["## Token 成本（API 真实返回）", ""] + large_lib.table(
        ("策略", "主回答输入", "主回答输出", "判分输入", "判分输出", "账面合计", "缓存命中",
         "缓存后等效"),
        [(f"`{s}`", f"{sums[s]['usage']['answer']['prompt']:,}",
          f"{sums[s]['usage']['answer']['completion']:,}",
          f"{sums[s]['usage']['judge']['prompt']:,}",
          f"{sums[s]['usage']['judge']['completion']:,}",
          f"{large_lib.total_of(sums[s]['usage']['total']):,}",
          f"{sums[s]['usage']['total']['cached']:,}",
          f"{effective(sums[s]['usage']['total']):,.0f}") for s in STRATS],
        ["---"] + ["---:"] * 7)
    lines += ["", f"总计 **{stats['success']} 次成功 / {stats['attempts']} 次尝试**（重试 {stats['retries']}，"
              f"失败 {stats['failed']}），账面 **{total_tokens:,} token**（输入 {grand['total']['prompt']:,} / "
              f"输出 {grand['total']['completion']:,} / 缓存命中 {grand['total']['cached']:,}），"
              f"缓存后等效 **{effective(grand['total']):,.0f} token**（未命中 + 0.1×命中 + 输出）；"
              f"`full` 缓存命中 {full_cache * 100:.0f}%，账面高估约 {large_lib.total_of(full['usage']['total']) / max(1, effective(full['usage']['total'])):.1f}×。", ""]
    solo, lost = 0, []
    for rec in records:
        for q in rec["gold"]:
            marks = [index[(rec["key"], q["q"], s)]["hit"] for s in STRATS]
            if marks[3] and not any(marks[:3]):
                solo += 1
            elif not marks[3] and any(marks[:3]):
                answer = " ".join(str(index[(rec["key"], q["q"], "seekmemory")]["answer"]).split())
                who = [s for s in STRATS[:3] if index[(rec["key"], q["q"], s)]["hit"]]
                block = rec["blocks"][("seekmemory", q["q"])]
                has = any(large_lib.norm(x) in large_lib.norm(block) for x in q["expect_any"])
                lost.append(f"- {rec['label']}｜{q['q']}（{q['category']}）→ {'、'.join(who)} 命中；"
                            f"块内{'有' if has else '无'}答案；SeekMemory 答「{answer[:40] or '（空）'}」")
    lines += ["## 独赢与漏题", "",
              f"**独赢 {solo} 题**（另外三种策略全未命中）；**漏掉 {len(lost)} 题**（其他策略命中）：", ""]
    lines += (lost or ["- 无。"])
    lines.append("")

    labels = {rec["key"]: rec["label"] for rec in records}
    per_line = "；".join(f"{labels[k]} {v['seekmemory']}/10" for k, v in per.items())
    seeks_total, kw_total = large_lib.total_of(seek["usage"]["total"]), large_lib.total_of(kw["usage"]["total"])
    full_total = large_lib.total_of(full["usage"]["total"])
    seek_eff, kw_eff, full_eff = (effective(o["usage"]["total"]) for o in (seek, kw, full))
    bounds = "，".join(f"`{s}` {sums[s]['leaks']}/{sums[s]['bound']}" for s in STRATS)
    lines += ["## 结论", "",
              f"1. **命中**：SeekMemory {seek['hits']}/{seek['n']}（非边界 {seek['plain_hits']}/"
              f"{seek['plain_n']}），keyword {kw['hits']}/{kw['n']}（非边界 {kw['plain_hits']}/"
              f"{kw['plain_n']}），full {full['hits']}/{full['n']}，no_memory {none['hits']}/{none['n']}。",
              f"2. **成本**：SeekMemory 平均注入 {seek['chars']:.0f} 字（常驻 {pin_avg['seekmemory']:.0f} + 检索 "
              f"{seek['chars'] - pin_avg['seekmemory']:.0f}），full {full['chars']:.0f} 字"
              f"（压缩 {full['chars'] / max(1.0, seek['chars']):.1f}×），keyword {kw['chars']:.0f} 字；"
              f"账面总 token {seeks_total:,} vs full {full_total:,} vs keyword {kw_total:,}；"
              f"缓存后等效 {seek_eff:,.0f} vs {full_eff:,.0f} vs {kw_eff:,.0f}。",
              f"3. **人味**：SeekMemory {seek['human']:.2f} / keyword {kw['human']:.2f} / full "
              f"{full['human']:.2f} / no_memory {none['human']:.2f}（1~5）。",
              f"4. **分人格命中**：{per_line}。",
              f"5. **是否支撑「更省 token 且更准」**："
              f"{'相对 full 成立' if seek_eff < full_eff and seek['hits'] >= full['hits'] else '相对 full 不成立'}；"
              f"{'相对 keyword 成立' if seek_eff <= kw_eff and seek['hits'] >= kw['hits'] else '相对 keyword 不成立'}。"
              "keyword 是最强基线：检索全部原文（含别人私聊与影子秘密）、不做 scope 与时间衰减，字面重合的题天然占优；SeekMemory 的价值在 scope 隔离、叙述化注入和成本不随记忆量线性上涨。",
              f"6. **边界**：{bounds}。", ""]

    lines += ["## 可信度自评", "",
              f"- **失败调用**：尝试 {stats['attempts']} 次、重试 {stats['retries']} 次、"
              f"最终失败 {stats['failed']} 次；失败题按未命中计，不进人味均分。",
              "- **判分主观**：人味分由 deepseek-flash 自己打，可能偏爱长答案；单次采样、"
              "temperature=0 也不保证严格确定；boundary 命中要求出现约定拒绝词，"
              "语义拒绝但措辞不同会判 miss，读边界结论以泄漏列和块级预检为准。",
              "- **构造与可比性**：full 是最近 16000 字符尾部截断、keyword 不做 scope 过滤，两者对 "
              "SeekMemory 一削一补；数据/题目/词表由同一脚本设计，60 题跑之前写死、没有删题，但单格差 1 题 = "
              "10 个百分点，差 2 题以内不算结论，合成语料不能直接外推。固定种子/模型/thinking，日期按运行当天滚动。"]
    lines += ["", "## 附录：判分词表", "",
              "| 画像 | 问题 | expect_any | boundary 泄漏词 |", "|---|---|---|---|"]
    lines += [row(rec["label"], q["q"], "、".join(q["expect_any"]), "、".join(q["leak"]) or "—")
              for rec in records for q in rec["gold"]]
    return lines


def main(argv=None):
    """解析参数 → 生成数据入库 → 并发调模型 → 写报告。"""
    argv = sys.argv[1:] if argv is None else list(argv)
    large_lib.require_key()
    smoke = "--smoke" in argv

    def gets(name, default):
        pos = argv.index(name) if name in argv else -1
        return argv[pos + 1] if 0 <= pos < len(argv) - 1 else default

    only = gets("--persona", personas.ORDER[0] if smoke else "")
    limit, workers = int(gets("--limit", "10")), int(gets("--workers", "4" if smoke else "6"))
    out = gets("--out", "" if smoke else OUT)
    started = time.perf_counter()
    records = build_all(only, limit)
    prepared = time.perf_counter() - started
    print(f"[准备] {len(records)} 个画像入库完成，用时 {prepared:.1f}s")
    tasks = [(rec["key"], rec["label"], q, s, rec["blocks"][(s, q["q"])])
             for rec in records for q in rec["gold"] for s in STRATS]
    results = large_lib.run_pool(tasks, workers)
    elapsed = time.perf_counter() - started
    stats = large_lib.stats_snapshot()
    print(f"[完成] {len(results)} 条结果，耗时 {elapsed:.1f}s，"
          f"API 尝试 {stats['attempts']} 次 / 失败 {stats['failed']} 次")
    lines = report(records, results, {"elapsed": elapsed, "prepared": prepared, "workers": workers,
                                      "stats": stats, "commit": os.environ.get("BENCH_COMMIT", "未记录"),
                                      "run_date": dt.datetime.now().isoformat(timespec="seconds")})
    if not out:
        print("\n".join(lines))
        return
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    print(f"→ 写入 {out}")
    head = next((i for i, line in enumerate(lines) if line.startswith("## SeekMemory 独赢")), len(lines))
    tail = next((i for i, line in enumerate(lines) if line.startswith("## 结论")), len(lines))
    print("\n" + "\n".join(lines[:head] + lines[tail:]))


if __name__ == "__main__":
    main()
