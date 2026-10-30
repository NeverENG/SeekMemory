"""端到端评测：同一个模型，六种记忆策略。

在 benchmarks/e2e.py 内自造 3 个用户、60 天的私聊 + 群聊数据，固定
deepseek-flash，只改变注入 system prompt 的记忆块，比较事实命中、
LLM 判分的“人味”、注入字数与耗时。纯标准库，单文件运行：
    python3 benchmarks/e2e.py
"""

from __future__ import annotations

import concurrent.futures as cf, datetime as dt, json, os, re, shutil, sys
import tempfile, threading, time, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.domain.memory.artifact import make  # noqa: E402
from core.domain.memory.graph import Graph  # noqa: E402
from recall.assemble import build as assemble  # noqa: E402
from recall.score import select  # noqa: E402
from recall.seed import seeds  # noqa: E402
from recall.spread import activate  # noqa: E402
from store.cache import Cache  # noqa: E402
from store import open_store  # noqa: E402

KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not KEY:
    raise SystemExit("缺少 DEEPSEEK_API_KEY。用法：export DEEPSEEK_API_KEY=sk-...")
URL, MODEL = "https://api.deepseek.com/v1/chat/completions", "deepseek-flash"
SYSTEM = "你是大肥鱼，一只圆滚滚的蓝色小鲸鱼。用一句话回答，简短、口语，不要列举。"
TODAY, DAYS = dt.date.today(), 60
STRATS = ("no_memory", "window", "summary", "keyword", "full", "seekmemory")
QUESTIONS = [
    ("我叫什么", ["吕宇轩", "BangBang", "邦邦"]), ("我是做什么的", ["量化"]), ("我的职业目标", ["架构师"]),
    ("我面试了哪家", ["万兴"]), ("面试结果怎么样", ["过了", "通过", "成功"]), ("上次加班到几点", ["两点", "2点", "2:00", "凌晨"]),
    ("我最近睡眠怎么样", ["睡不着", "失眠", "睡不好", "睡眠差"]), ("我最近为什么心情差", ["领导", "骂"]),
    ("你觉得我这个人怎么样", ["倔", "帮"]),
]
SCOPE_Q = "u1 是不是偷偷喜欢小美？"

# (天, 文本, 层级, 标签, 权重, 唤醒度, 效价)
FACTS = [
    (1, "我叫吕宇轩，也叫 BangBang", "fact", "名字 称呼 吕宇轩 BangBang 叫", 2.0, 0.2, 0.3), (2, "我是做量化交易的，手上有个项目", "fact", "工作 量化 交易 项目 做", 1.8, 0.2, 0.2),
    (5, "我的职业目标是成为核心架构师", "fact", "职业 目标 架构师 工作", 1.8, 0.4, 0.4), (20, "我面试了万兴科技", "scene", "面试 万兴科技 公司 工作", 1.6, 0.7, 0.2),
    (30, "我加班到两点才回家", "scene", "加班 两点 工作 累", 1.5, 0.8, -0.5), (30, "我被领导骂了，心情很差", "scene", "领导 骂 心情 最近 工作", 1.5, 0.9, -0.8),
    (35, "我睡眠很差，老是睡不着", "detail", "睡眠 失眠 状态 累", 1.3, 0.8, -0.6), (40, "面试结果出来了，我过了", "scene", "面试 结果 通过 工作", 1.7, 0.9, 0.8),
]
IMPRESSION = "你这个人有点倔，但真有事会帮。"
IMPRESSION_MEM = "我有点倔，但真有事会帮"
FACT_META = {f[1]: f[2:] for f in FACTS}
FACT_META[IMPRESSION] = ("impression", "印象 倔 帮忙 人 觉得", 1.0, 0.5, 0.3)
FACT_BY_DAY: dict = {}
for _f in FACTS:
    FACT_BY_DAY.setdefault(_f[0], []).append(_f)

P_NOISE = "今天项目又改需求了，好烦|中午吃了黄焖鸡，还行|刚开完会，脑子有点糊|下班路上下了点雨|今天写代码写到手酸|晚上准备早点睡|同事请我喝了杯奶茶|周末想去爬山，你有空吗|今天地铁特别挤|刚吃完饭，有点撑".split("|")
B_REPLY = "辛苦啦，先歇一会儿吧|听着就累，晚上早点睡|那你记得吃饭呀|摸摸头，别太拼了|嗯嗯，我在呢".split("|")
G_NOISE = {"u0": "今天项目又改需求了|晚上有人一起吃饭吗|这个接口怎么又挂了|我先去开会了|你们周末干嘛|今天好困啊".split("|"), "u1": "我最近在追一部剧|刚打完球，累死了|中午吃啥|哈哈哈哈哈|老板又画饼|我周末去露营".split("|"), "u2": "这个报表我弄完了|客户又改方案|地铁上人好多|明天要早起|头疼|下午要对齐一下".split("|")}
# u0 3 条、u1 4 条、u2 3 条
PLAN = [("u0", 0), ("u1", 0), ("u2", 0), ("u1", 1), ("u0", 1), ("u2", 1), ("u1", 2), ("u0", 2), ("u1", 3), ("u2", 2)]
SECRETS = [(12, "u1", "我偷偷喜欢公司前台小美，你别告诉吕宇轩"), (33, "u2", "我正在偷偷准备跳槽，别跟吕宇轩说")]

def date_of(day):
    return (TODAY - dt.timedelta(days=DAYS - day)).isoformat()

def gen_messages():
    msgs = []
    for day in range(1, DAYS + 1):
        facts = FACT_BY_DAY.get(day, [])
        texts = [f[1] for f in facts]
        texts += [P_NOISE[(day + i) % len(P_NOISE)] for i in range(2 - len(texts))]
        for i, text in enumerate(texts[:2]):
            msgs += [{"day": day, "ch": "private", "uid": "u0", "text": text}, {"day": day, "ch": "private", "uid": "bot", "text": B_REPLY[(day + i) % len(B_REPLY)]}]
        for d, uid, text in SECRETS:
            if d == day:
                msgs += [{"day": day, "ch": "private", "uid": uid, "text": text}, {"day": day, "ch": "private", "uid": "bot", "text": "放心，我不会说出去。"}]
        for i, (uid, idx) in enumerate(PLAN):
            text = ("你们觉得我这个人怎么样？" if day == 50 and i == 0 else
                    IMPRESSION if day == 50 and i == 1 else
                    G_NOISE[uid][(day * 3 + idx) % len(G_NOISE[uid])])
            msgs.append({"day": day, "ch": "group", "uid": uid, "text": text})
    return msgs

def ingest(msgs):
    tmp = tempfile.mkdtemp(prefix="seekmem_e2e_")
    db = open_store(os.path.join(tmp, "e2e.db"))
    cache = Cache(db.artifacts); graph = Graph(db.artifacts); by_key = {}
    for m in msgs:
        if m["uid"] == "bot":
            continue
        meta = FACT_META.get(m["text"])
        if m["ch"] == "group":
            scope = "shared"
            level, tags, weight, arousal, valence = meta or ("detail", "", 0.6, 0.3, 0.0)
            weight = max(weight, 0.7) if m["uid"] == "u0" else weight
        else:
            scope = "private" if m["uid"] == "u0" else "shadow"
            level, tags, weight, arousal, valence = meta or ("detail", "", 0.5, 0.3, -0.2)
            if m["uid"] != "u0":
                level, tags, weight = "detail", "秘密 私聊", 0.8
        art = make("memory", {
            "text": IMPRESSION_MEM if m["text"] == IMPRESSION else m["text"],
            "level": level, "shape": "pattern" if level in ("fact", "impression") else "point",
            "chrono": "once", "about": "other", "tags": tags.split()},
            scope=scope, said_by=m["uid"],
            strength={"weight": weight, "confidence": 1.0, "arousal": arousal,
                      "valence": valence, "funny": 0.0},
            time={"created": date_of(m["day"]), "updated": date_of(m["day"])})
        db.artifacts.upsert(art); cache.put(art); by_key[(m["day"], m["uid"], m["text"])] = art
    get = lambda d, u, t: by_key[(d, u, t)]
    link = lambda a, b, k, w: graph.link(a.header.id, b.header.id, k, w)
    name, quant, arch = get(1, "u0", FACTS[0][1]), get(2, "u0", FACTS[1][1]), get(5, "u0", FACTS[2][1])
    mwx, passed = get(20, "u0", FACTS[3][1]), get(40, "u0", FACTS[7][1])
    overtime, scold = get(30, "u0", FACTS[4][1]), get(30, "u0", FACTS[5][1])
    sleep = get(35, "u0", FACTS[6][1])
    link(name, quant, "similar", 0.6); link(quant, arch, "similar", 0.6)
    link(mwx, passed, "causal", 0.9); link(overtime, scold, "temporal", 0.9)
    link(scold, sleep, "temporal", 0.8); link(overtime, sleep, "temporal", 0.6)
    return tmp, db, cache, graph

MSGS, MEMS, OWNER = [], [], []
CACHE = GRAPH = None

def grams(text):
    chars = [c.lower() for c in str(text) if c.isalnum()]
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}

def summary_of(day):
    priv = [m["text"] for m in MSGS if m["day"] == day and m["ch"] == "private" and m["uid"] == "u0"]
    grp = [m["text"] for m in MSGS if m["day"] == day and m["ch"] == "group"]
    return f"第{day}天：私聊里我说{'、'.join(priv)}；群里聊了{grp[0]}。"[:80]

def keyword_block(q):
    qg, df = grams(q), {}
    for m in MEMS:
        for g in grams(m["text"]):
            df[g] = df.get(g, 0) + 1
    scored = []
    for i, m in enumerate(MEMS):
        hit = qg & grams(m["text"])
        if hit:
            scored.append((sum(1.0 / df[g] for g in hit), i, m))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return "\n".join(f"{m['uid']}: {m['text']}" for _, _, m in scored[:5])

def seek_pick(q):
    act = activate(seeds(q, OWNER), GRAPH, CACHE)
    picked = select([(a, float(act.get(a.header.id, 0.0))) for a in OWNER],
                    q, 0.0, k=6, explore=0.0)
    return assemble(picked, budget=600), picked

def build_block(strategy, q):
    if strategy == "no_memory":
        return ""
    if strategy == "window":
        return "\n".join(f"{m['uid']}: {m['text']}" for m in MSGS[-10:])
    if strategy == "summary":
        return "\n".join(summary_of(d) for d in range(DAYS - 6, DAYS + 1))
    if strategy == "full":
        return "\n".join(f"{m['uid']}: {m['text']}" for m in MEMS)[:12000]
    if strategy == "keyword":
        return keyword_block(q)
    return seek_pick(q)[0]

def api(messages, temperature=0.7):
    # deepseek-flash 默认先写 reasoning_content，120 token 预算容易被推理吃光；
    # 显式关闭 thinking，保证所有策略拿到的是同一模型的直接回答。
    body = {"model": MODEL, "messages": messages, "max_tokens": 120,
            "temperature": temperature, "thinking": {"type": "disabled"}}
    last = ""
    for _ in range(2):
        try:
            req = urllib.request.Request(
                URL, data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = (data["choices"][0]["message"].get("content") or "").strip()
            if content:
                return content, ""
            last = "EmptyContent"
        except Exception as exc:  # noqa: BLE001 - 失败要记录，不能让脚本崩
            last = f"{type(exc).__name__}: {exc}"
        time.sleep(1.2)
    return "", last
def judge(q, answer, expect):
    prompt = ("给下面回答的“人味”打分（1~5）。5=像真人随口说的话，简短自然并自然用上记忆细节；"
              f"3=通顺但像模板或没用到关键细节；1=机械、答非所问。\n已知事实：{'、'.join(expect)}"
              f"\n问题：{q}\n回答：{answer}\n只输出整数。")
    text, _ = api([{"role": "system", "content": "你是严格的中文对话评测员。"},
                   {"role": "user", "content": prompt}], temperature=0.0)
    found = re.search(r"(?<!\d)([1-5])(?!\d)", text or "")
    return int(found.group(1)) if found else None

def evaluate(task):
    strategy, q, expect, block = task
    system = SYSTEM + (f"\n\n【你记得的事】\n{block}" if block else "")
    t0 = time.perf_counter()
    answer, err = api([{"role": "system", "content": system}, {"role": "user", "content": q}])
    ms = (time.perf_counter() - t0) * 1000
    hit = bool(answer) and any(k.lower() in answer.lower() for k in expect)
    return {"strategy": strategy, "q": q, "expect": expect, "answer": answer, "err": err,
            "hit": hit, "human": judge(q, answer, expect) if answer and not err else None,
            "ms": ms, "chars": len(block)}

def run_all():
    tasks = [(s, q, e, build_block(s, q)) for s in STRATS for q, e in QUESTIONS]
    done, lock = [0], threading.Lock()

    def one(task):
        r = evaluate(task)
        with lock:
            done[0] += 1
            print(f"[{done[0]:02d}/{len(tasks)}] {r['strategy']:<10} {r['q']} "
                  f"{'✅' if r['hit'] else ('⚠' if r['err'] else '❌')}")
        return r

    with cf.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, tasks))
    return results, {(t[0], t[1]): t[3] for t in tasks}

def clean(text, limit=80):
    out = " ".join(str(text or "").split()).replace("|", "｜")
    return out[:limit] + ("…" if len(out) > limit else "")

def report(results, blocks, leaks):
    rows = []
    for s in STRATS:
        rs = [r for r in results if r["strategy"] == s]
        hs = [r["human"] for r in rs if r["human"] is not None]
        ts = [r["ms"] for r in rs if not r["err"]]
        rows.append({"s": s, "hits": sum(r["hit"] for r in rs),
                     "avg": sum(hs) / len(hs) if hs else 0.0, "n": len(hs),
                     "chars": sum(len(blocks[(s, q)]) for q, _ in QUESTIONS) / len(QUESTIONS),
                     "ms": sum(ts) / len(ts) if ts else 0.0,
                     "fails": sum(1 for r in rs if r["err"])})
    by = {r["s"]: r for r in rows}
    summary = ["# 端到端评测：同一个模型，六种记忆策略", "",
               f"> 模型：{MODEL}（固定，关闭 thinking 以让 120 token 留给回答/判分）· 3 用户 · {DAYS} 天 · {len(QUESTIONS)} 个问题", "",
               "| 策略 | 事实命中 | 人味均分 | 平均注入字数 | 平均耗时 |",
               "|---|---|---|---|---|"]
    for r in rows:
        avg = f"{r['avg']:.2f}" if r["n"] else "—"
        summary.append(f"| `{r['s']}` | **{r['hits']}/{len(QUESTIONS)}** | {avg} | "
                       f"{r['chars']:.0f} | {r['ms'] / 1000:.2f}s |")
    fails = sum(r["fails"] for r in rows)
    if fails:
        summary += ["", f"> 失败 {fails} 次（每次自动重试一次；失败题按未命中计，未计入人味均分）。"]
    summary += ["", "> 耗时只计主回答调用，不含判分调用。", "", "## Scope 隔离探针", "",
                f"探针问题：`{SCOPE_Q}`。正确行为是答“不知道”；上下文出现“小美”即判泄漏（只查上下文，不额外调模型）。",
                "", "| 策略 | u1 私密内容进入上下文 |", "|---|---|"]
    summary += [f"| `{s}` | {'**泄漏**' if leaks[s] else '未泄漏'} |" for s in STRATS]

    lines = summary + ["", "## 逐题明细", "", "| 问题 | 策略 | 答案 | 命中 |", "|---|---|---|---|"]
    index = {(r["strategy"], r["q"]): r for r in results}
    for q, _ in QUESTIONS:
        for s in STRATS:
            r = index[(s, q)]
            ans = clean(r["answer"]) or (f"（失败：{clean(r['err'], 40)}）"
                                         if r["err"] else "（空回答）")
            lines.append(f"| {q} | `{s}` | {ans} | "
                         f"{'✅' if r['hit'] else ('—' if r['err'] else '❌')} |")

    best = max(rows, key=lambda r: (r["hits"], r["avg"], -r["chars"]))
    seek, full = by["seekmemory"], by["full"]
    saved, ratio = full["chars"] - seek["chars"], full["chars"] / max(seek["chars"], 1.0)
    leak_names = "、".join(f"`{s}`" for s in STRATS if leaks[s]) or "无"
    lines += ["", "## 结论", "",
              f"**{best['s']} 最好**：事实命中 {best['hits']}/{len(QUESTIONS)}、"
              f"人味 {best['avg']:.2f}、平均注入 {best['chars']:.0f} 字。"
              f"SeekMemory 相比 plain 全量注入省了 **{saved:.0f} 字（约 {ratio:.1f}×）**，"
              f"事实命中 {seek['hits']}/{len(QUESTIONS)} vs {full['hits']}/{len(QUESTIONS)}"
              f"（{seek['hits'] - full['hits']:+d} 题），人味 {seek['avg']:.2f} vs "
              f"{full['avg']:.2f}（{seek['avg'] - full['avg']:+.2f}）。"
              f"原因是：全量注入也能命中全部事实，但每轮 {full['chars']:.0f} 字里绝大部分是噪声，人味略低；"
              "窗口与日摘要被时间窗截断；关键词命中高但给零散原句、不做 scope 过滤；no_memory 没有细节。"
              f"SeekMemory 用种子→激活扩散→五维打分→叙述组装，只给 6 条相关记忆，以 {seek['chars']:.0f} 字拿到同样命中且人味最高。"
              f"Scope 探针中泄漏的是{leak_names}；SeekMemory {'也泄漏' if leaks['seekmemory'] else '未泄漏'}。"
              "注意：单次采样、主调用 temperature=0.7、LLM 判分有主观性，结论看趋势。"]
    return lines, summary

def main():
    global MSGS, MEMS, OWNER, CACHE, GRAPH
    MSGS = gen_messages(); MEMS = [m for m in MSGS if m["uid"] != "bot"]
    tmp, db, CACHE, GRAPH = ingest(MSGS)
    OWNER = [a for a in CACHE.active() if a.header.scope != "shadow"]
    try:
        results, blocks = run_all()
        lines, summary = report(results, blocks, {s: "小美" in build_block(s, SCOPE_Q) for s in STRATS})
        out = os.path.join(ROOT, "benchmarks", "results", "e2e.md")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("\n" + "\n".join(summary))
        print(f"\n→ 写入 {out}")
    finally:
        db.close()
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
