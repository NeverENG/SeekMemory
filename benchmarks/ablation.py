"""消融基准：逐个关掉检索组件，看黄金集召回掉多少。

不修改核心代码：打分项靠「给 select 传入改造过的候选」关闭，去重 / 时间
衰减靠 with 里临时替换、退出即还原，层级只在组装时抹掉。九种配置跑同一
份数据、同一份黄金集，输出 .tmp/benchmarks/<运行编号>/ablation.md。

用法：python3 benchmarks/ablation.py
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from dataclasses import dataclass, replace
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import recall.assemble as assemble_mod  # noqa: E402
import recall.gate as gate_mod, recall.score as score_mod  # noqa: E402
from benchmarks.output import report_path
from benchmarks.edge_stats import spread_counts  # noqa: E402
from benchmarks.goldset import FORBIDDEN, GOLD, SEED, TODAY, build, noise_share  # noqa: E402
from core.artifact import Artifact, content_of, make  # noqa: E402
from core.graph import Graph  # noqa: E402
from maintain.link import persist  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.score import select  # noqa: E402
from recall.bm25 import BM25Index  # noqa: E402
from recall.retriever import HybridRetriever  # noqa: E402
from recall.seed import bigrams, dice, seeds  # noqa: E402
from recall.spread import activate  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import Store, open_store  # noqa: E402

K, BUDGET = 8, 600


@dataclass(frozen=True)
class Cfg:
    """一种消融配置：名字 + 要关掉的组件（True 表示保留）。"""

    name: str
    spread: bool = True
    emotion: bool = True
    tag: bool = True
    weight: bool = True
    dedupe: bool = True
    layer: bool = True
    decay: bool = True
    literal_only: bool = False
    gate: bool = True  # 相关性双阈值闸门（ISSUE-0017）
    bm25: bool = False
    calibration_c: float = 8.0
    lexical_weight: float = 1.0


CONFIGS = (
    Cfg("full"),
    Cfg("bm25_on", bm25=True),
    Cfg("no_gate", gate=False),
    Cfg("no_spread", spread=False),
    Cfg("no_score_emotion", emotion=False),
    Cfg("no_score_tag", tag=False),
    Cfg("no_weight_prior", weight=False),
    Cfg("no_dedupe", dedupe=False),
    Cfg("no_layer", layer=False),
    Cfg("no_decay", decay=False),
    Cfg("literal_only", spread=False, emotion=False, tag=False, weight=False,
        literal_only=True),
)


def _artifact(m) -> Artifact:
    """Mem -> Artifact；fact / impression 用 pattern 形状（衰减更慢）。"""
    d = (date.today() - timedelta(days=TODAY - m.day)).isoformat()
    payload = {"text": m.text, "level": m.level, "chrono": "once", "about": "other",
               "shape": "pattern" if m.level in ("fact", "impression") else "point",
               "tags": list(m.tags)}
    return make("memory", payload, scope=m.scope,
                strength={"weight": m.weight, "confidence": 1.0, "arousal": m.arousal,
                          "valence": m.valence, "funny": 0.0},
                time={"created": d, "updated": d})


def _load(mems) -> tuple[Store, Cache, Graph, list[Artifact]]:
    """走生产写入路径建 similar/temporal 边；causal 仍由人工金标补。"""
    db = open_store(":memory:")
    try:
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)
        for m in mems:
            persist(_artifact(m), db.artifacts, cache, graph)
        pool = cache.active()
        by_text = {str(a.payload.get("text")): a for a in pool}
        if os.environ.get("ABLATION_NO_CAUSAL") != "1":
            graph.link(by_text["他去万兴科技面试了"].header.id,
                       by_text["万兴那边给他发了offer，他过了"].header.id, "causal", .9)
        return db, cache, graph, pool
    except BaseException:
        db.close()
        raise


def _transform(cfg: Cfg, pool: list[Artifact]) -> list[Artifact]:
    """把要关掉的打分项从候选上「物理」摘掉，不改核心代码。"""
    if not cfg.literal_only and cfg.emotion and cfg.tag and cfg.weight:
        return pool
    out = []
    for art in pool:
        payload = dict(art.payload)
        strength = art.header.strength
        if cfg.literal_only or not cfg.tag:
            for key in ("tags", "tag", "last_used", "hot_until", "used_at"):
                payload.pop(key, None)
        if cfg.literal_only or not cfg.emotion:
            strength = replace(strength, arousal=0.0, valence=0.0, funny=0.0)
        if cfg.literal_only or not cfg.weight:
            strength = replace(strength, weight=0.0)
        out.append(Artifact(replace(art.header, strength=strength), payload))
    return out


def _without_level(art: Artifact) -> Artifact:
    """no_layer：组装时假装没有 level，所有记忆平铺。"""
    return Artifact(art.header, {k: v for k, v in art.payload.items() if k != "level"})


@contextlib.contextmanager
def _clock(cfg: Cfg):
    """临时改时间衰减：no_decay 全部新鲜，literal_only 全部过期。"""
    old = score_mod._age_days
    if cfg.literal_only or not cfg.decay:
        score_mod._age_days = (lambda c, n: 1e6) if cfg.literal_only else (lambda c, n: 0.0)
    try:
        yield
    finally:
        score_mod._age_days = old


@contextlib.contextmanager
def _dedupe(cfg: Cfg):
    """临时关掉 assemble 的全局去重（退出即还原）。"""
    old = assemble_mod._dedupe
    if not cfg.dedupe:
        assemble_mod._dedupe = lambda arts: list(arts)
    try:
        yield
    finally:
        assemble_mod._dedupe = old


def pipeline(cfg: Cfg, pool, source, graph, cache, q: str,
             hybrid: HybridRetriever | None = None) -> tuple[str, list, list]:
    """按配置组合 seeds → activate → select → assemble，返回注入文本、检索层与常驻层。"""
    if cfg.bm25:
        retriever = hybrid or HybridRetriever(graph, cache, BM25Index(cfg.calibration_c))
        candidates = retriever.retrieve(q, pool)
    elif cfg.literal_only:
        qg = bigrams(q)
        candidates = [(a, 0.0) for a in pool
                      if dice(qg, len(qg), frozenset(bigrams(content_of(a)))) > 0]
    else:
        seed_ids = seeds(q, source)
        activation = activate(seed_ids, graph, cache) if cfg.spread else {}
        candidates = [(a, float(activation.get(a.header.id, 0.0))) for a in pool]
    with _clock(cfg):
        picked = select(candidates, q, 0.0, k=K, explore=0.0, gate=cfg.gate,
                        lexical_weight=cfg.lexical_weight)
    if not cfg.layer:
        picked = [_without_level(a) for a in picked]
    pin = gate_mod.pinned(cache)
    with _dedupe(cfg):
        return assemble(pin + picked, budget=BUDGET), picked, pin


def measure(cfg: Cfg, pool, source, graph, cache) -> dict:
    """跑完 20 条黄金问句，分别统计常驻层 / 检索层的字数与检索层噪声。"""
    hit = total = chars = leak = bchars = pin_chars = ret_chars = 0
    boundary_n = sum(1 for g in GOLD if not g["expect_any"])
    noise_chars = kept_chars = 0
    misses = []
    elapsed = 0.0
    hybrid = HybridRetriever(graph, cache, BM25Index(cfg.calibration_c)) if cfg.bm25 else None
    for g in GOLD:
        started = time.perf_counter()
        block, picked, pin = pipeline(cfg, pool, source, graph, cache, g["q"], hybrid)
        elapsed += time.perf_counter() - started
        low, exps = block.lower(), [e.lower() for e in g["expect_any"]]
        chars += len(block)
        ok = bool(exps) and any(e in low for e in exps)
        pin_ids = {id(art) for art in pin}
        kept = (pin + picked) if not cfg.dedupe else assemble_mod._dedupe(pin + picked)
        for art in kept:
            try:
                n = len(assemble_mod._sentence(art)[1])
            except Exception:  # noqa: BLE001 - 坏条目按正文长度兜底
                n = len(content_of(art))
            if id(art) in pin_ids:
                pin_chars += n
                continue
            ret_chars += n
            if exps:
                kept_chars += n
                if not any(e in content_of(art).lower() for e in exps):
                    noise_chars += n
        if exps:
            total += 1
            hit += ok
            if not ok:
                misses.append(g["q"])
        else:
            leak += sum(low.count(w) for w in FORBIDDEN.get(g["q"], ()))
            bchars += len(block)
    return {"name": cfg.name, "hit": hit, "total": total, "misses": misses,
            "chars": chars / len(GOLD), "pin_chars": pin_chars / len(GOLD),
            "ret_chars": ret_chars / len(GOLD), "noise": noise_chars / max(1, kept_chars),
            "leak": leak, "bchars": bchars / max(1, boundary_n),
            "latency_ms": elapsed * 1000 / len(GOLD)}


def report(results: list[dict], stats: dict) -> str:
    """生成 markdown 报告：结果表 + 逐项解读 + 结论。"""
    rs = sorted(results, key=lambda r: (-r["hit"], r["noise"], r["chars"]))
    base = next(r for r in rs if r["name"] == "full")
    cats: dict[str, int] = {}
    for g in GOLD:
        key = g["note"].split("｜")[0]
        cats[key] = cats.get(key, 0) + 1
    why = {"事实·跨表述": "与问句零字面重合，考混合检索", "事实": "名字、目标、家乡、游戏、宠物",
           "事件": "面试、加班、请客；部分靠关系边扩散", "情绪": "低潮、失眠；正向状态作干扰",
           "印象": "「倔」「心软」；高权重低字面", "边界": "应返回空：别人的秘密、短期琐事"}
    L = ["# 消融基准：每个组件值多少", "",
         f"> {stats['n']} 条消息（{stats['noise']:.0%} 是模板闲聊）· 20 条黄金问答（18 条可答 + 2 条边界）· 固定种子 {SEED}",
         f"> {stats['edges']} 条边（自动 similar/temporal + {stats['causal']} 人工 causal）· 扩散新增 {stats['spread'][0]}（{stats['spread'][1]}/20 题）",
         "> 检索参数：top-k=8、注入预算 600 字、explore=0；常驻层（persona + 印象前 2）不经闸门",
         f"> 证据闸门：`evidence >= max({gate_mod.MIN_EV_ABS}, top_evidence × {gate_mod.MIN_EV_REL})`；weight/freshness 只排序", "",
         "## 黄金集", "", "| 类别 | 题数 | 考什么 |", "|---|---:|---|"]
    L += [f"| {c} | {n} | {why[c]} |" for c, n in cats.items()]
    L += ["", f"数据里 {stats['noise_text']}/{stats['n']} 条是模板生成的无关闲聊，"
          "非闲聊只有 20 条；这保证命中不是靠「池子里全是答案」。", "",
          "## 消融结果", "",
          "| 配置 | 命中 | 总注入 | 常驻层 | 检索层 | 检索层噪声 | 边界正文泄露 | 边界注入 | 平均耗时 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    L += [f"| `{r['name']}` | **{r['hit']}/{r['total']}** | {r['chars']:.0f} 字 | {r['pin_chars']:.0f} 字 | "
          f"{r['ret_chars']:.0f} 字 | {r['noise']:.2%} | {r['leak']} | {r['bchars']:.0f} 字 | "
          f"{r['latency_ms']:.3f} ms |" for r in rs]
    L += ["", "> 「命中」按 18 条可答题计；边界题单列「边界正文泄露」（FORBIDDEN 词次数，红线 0）与注入字数。",
          "> 字数是 20 条问句的平均值。**噪声只统计检索层**：常驻层是固定画像开销，混进噪声会逼着砍人格。",
          "", "## 逐项解读", ""]
    explain = {
        "full": "证据闸门生效后的检索层基线：命中由字面/标签/激活/情绪证据决定；常驻层是固定画像，不经闸门。",
        "bm25_on": "开启纯本地 BM25（C=8，weight=1），复用既有图激活、评分和证据闸门。",
        "no_gate": "关掉闸门即旧 top-k 行为：检索层噪声与字数回到未过滤水平；多出的命中靠凑满 top-8。",
        "no_spread": "激活扩散是证据之一：关掉后「面试结果」（靠 causal 边拿到 offer）与「我是不是嘴硬心软」掉出闸门。",
        "no_score_emotion": "情绪对齐算证据：关掉后带情绪词的问句失去匹配信号，面试结果、累、印象类共 4 条掉出闸门。",
        "no_score_tag": "标签是零字面事实的主要证据：关掉后名字/职业/家乡/游戏/睡眠等只剩字面，7 条掉出闸门。",
        "no_weight_prior": "权重不参与闸门，关掉只改排序：命中与 full 一致——这正是证据闸门修掉的老问题。",
        "no_dedupe": "命中不变，重复条目略增字数和噪声；闸门后注入本来就少，去重收益变小。",
        "no_layer": "level 只影响 assemble 的排序和措辞，不进证据；命中不变。",
        "no_decay": "freshness 只参与排序、不进证据；关掉后排名不翻转，命中不变。",
        "literal_only": "只剩字面证据时，只有问句带原词的题能过门；它的问题是找不到，不是找错。",
    }
    for r in rs:
        miss = "没有漏题。" if not r["misses"] else "漏掉：" + "、".join(f"「{q}」" for q in r["misses"]) + "。"
        L.append(f"**`{r['name']}`** — 命中 {r['hit']}/{r['total']}（{r['hit'] - base['hit']:+d}），"
                 f"平均注入 {r['chars']:.0f} 字，噪声 {r['noise']:.0%}，"
                 f"边界泄露 {r['leak']}、注入 {r['bchars']:.0f} 字。"
                 f"{explain[r['name']]}{miss}")
        L.append("")
    L += ["", "## 结论", "", _conclusion(base, {r["name"]: r for r in rs})]
    return "\n".join(L) + "\n"


def _conclusion(base: dict, by: dict) -> str:
    """按实测差值写结论，不写死数字。"""
    loss = {n: base["hit"] - r["hit"] for n, r in by.items() if n != "full"}
    ng = by["no_gate"]
    misses = "、".join(f"「{q}」" for q in base["misses"]) or "无"
    return "\n".join([
        f"1. **证据是检索层的唯一入场券**：关掉标签掉 {loss['no_score_tag']} 条、情绪掉 {loss['no_score_emotion']} 条、"
        f"激活掉 {loss['no_spread']} 条；只留字面时只剩 {by['literal_only']['hit']}/18。权重/新鲜度/层级只排序。",
        f"2. **闸门买的是精度**：`full` 检索层噪声 {base['noise']:.0%}、{base['ret_chars']:.0f} 字；`no_gate` 噪声 "
        f"{ng['noise']:.0%}、{ng['ret_chars']:.0f} 字；命中 {base['hit']}/18 vs {ng['hit']}/18（后者凑满 top-8 带进零证据题）。",
        f"3. **常驻层是固定开销**：两个配置都注入 {base['pin_chars']:.0f} 字/轮"
        f"（persona + 印象前 2，不经闸门），总注入 = 常驻 + 检索。印象题命中有一部分来自常驻层，"
        f"不算闸门功劳；仍掉的零证据题是 {misses}，归 ISSUE-0001。",
        f"4. **边界**：正文泄露 {base['leak']}（`no_gate` {ng['leak']}）。不看注入块是否为空——"
        "时钟题不检索，常驻层照常注入；影子题只输出遮蔽句是 DESIGN 7.4 行为。",
        "",
        f"一句话：**证据闸门把 weight/freshness 从检索里拆出来，常驻层单独计价；检索层噪声 {ng['noise']:.0%}→{base['noise']:.0%} 的代价是零证据题，留给混合检索。**", ""])


def main() -> None:
    mems = build()
    stats = {"n": len(mems), "noise": noise_share(mems),
             "noise_text": sum(1 for m in mems if m.noise)}
    db, cache, graph, source = _load(mems)
    stats["edges"] = db.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    stats["causal"] = db.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE kind = 'causal'").fetchone()[0]
    stats["spread"] = spread_counts(source, graph, cache, GOLD)
    try:
        results = []
        for cfg in CONFIGS:
            results.append(measure(cfg, _transform(cfg, source), source, graph, cache))
            r = results[-1]
            print(f"[{cfg.name:<16}] 命中 {r['hit']}/{r['total']} 总注入 {r['chars']:.0f} 常驻 {r['pin_chars']:.0f} "
                  f"检索 {r['ret_chars']:.0f} 检索噪声 {r['noise']:.0%} 泄露 {r['leak']}")
        out = report_path("ablation")
        with open(out, "w", encoding="utf-8") as f:
            f.write(report(results, stats))
        print(f"\n→ 写入 {out}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
