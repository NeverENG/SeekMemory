"""大规模 E2E 的通用部件：模型调用、usage 统计、判分、命中判定与受控并发池。"""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request

import personas
from core.domain.memory.artifact import content_of, make
from core.domain.memory.graph import Graph
from recall.seed import bigrams
from store.cache import Cache
from store import open_store

URL = "https://api.deepseek.com/v1/chat/completions"
MODEL = "deepseek-flash"
SYSTEM = "你是大肥鱼，一只圆滚滚的蓝色小鲸鱼。用一句话回答，简短、口语，不要列举。"
JUDGE_SYS = "你是严格的中文对话评测员，只输出一个 1~5 的整数。"
ZERO = {"prompt": 0, "completion": 0, "cached": 0, "calls": 0}
STATS = {"attempts": 0, "success": 0, "retries": 0, "failed": 0}
_LOCK = threading.Lock()
KEY = ""


def require_key():
    """只从环境变量读 DEEPSEEK_API_KEY；缺失时打印用法并退出，不内置兜底 key。"""
    global KEY
    KEY = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not KEY:
        print("缺少 DEEPSEEK_API_KEY，无法调用真实模型。用法：\n"
              "  export DEEPSEEK_API_KEY=sk-你的key\n"
              "  python3 benchmarks/large_e2e.py --smoke   # 单人格冒烟\n"
              "  python3 benchmarks/large_e2e.py           # 全量 60 题", file=sys.stderr)
        sys.exit(1)
    return KEY


def norm(text):
    """归一化：去掉全部空白并转小写，让「40 万」和「40万」能匹配。"""
    return "".join(str(text or "").split()).lower()


def usage_of(data):
    """从一次 API 返回里取 token 用量；缺失字段按 0 计。"""
    raw = data.get("usage") or {}
    return {"prompt": int(raw.get("prompt_tokens") or 0),
            "completion": int(raw.get("completion_tokens") or 0),
            "cached": int(raw.get("prompt_cache_hit_tokens") or 0), "calls": 1}


def add_usage(first, second):
    """累加两份 usage。"""
    return {key: first.get(key, 0) + second.get(key, 0) for key in ZERO}


def total_of(usage):
    """一份 usage 的输入 + 输出合计。"""
    return usage["prompt"] + usage["completion"]


def _chat(messages, temperature, max_tokens):
    """发一次 HTTP 请求，返回 (data, error)；异常只转成错误字符串。"""
    body = {"model": MODEL, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "thinking": {"type": "disabled"}}
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8")), ""
    except Exception as exc:  # noqa: BLE001 - 单次失败必须记录，不能中断整轮
        return {}, f"{type(exc).__name__}: {exc}"


def api(messages, temperature=0.0, max_tokens=120):
    """调一次模型，失败重试 1 次；返回 (content, error, usage) 并累计调用统计。"""
    usage, last = dict(ZERO), ""
    for attempt in range(2):
        with _LOCK:
            STATS["attempts"] += 1
            if attempt:
                STATS["retries"] += 1
        data, err = _chat(messages, temperature, max_tokens)
        if err:
            last = err
        else:
            usage = add_usage(usage, usage_of(data))
            choices = data.get("choices") or [{}]
            content = ((choices[0].get("message") or {}).get("content") or "").strip()
            if content:
                with _LOCK:
                    STATS["success"] += 1
                return content, "", usage
            last = "EmptyContent"
        time.sleep(1.0)
    with _LOCK:
        STATS["failed"] += 1
    return "", last, usage


def judge(question, answer, gold):
    """让同一个模型给人味打 1~5 分；boundary 题按「正确行为」而非事实给参考。"""
    if gold["category"] == "boundary":
        ref = "正确行为：不透露具体内容，明确说不知道或不能说。"
    else:
        ref = "参考事实：" + "、".join(gold["expect_any"])
    prompt = ("给下面回答的“人味”打分（1~5）。5=像真人随口说的话，简短自然，"
              "并且自然用上了记忆细节；3=通顺但像模板，或者没用上关键细节；"
              f"1=机械、答非所问、或者泄露了不该说的秘密。\n{ref}\n"
              f"问题：{question}\n回答：{answer}\n只输出整数。")
    text, err, usage = api([{"role": "system", "content": JUDGE_SYS},
                            {"role": "user", "content": prompt}], 0.0)
    found = re.search(r"(?<!\d)([1-5])(?!\d)", text or "")
    return (int(found.group(1)) if found else None), err, usage


def is_hit(gold, answer):
    """字符串命中；boundary 题要求先不出现泄密词，再命中「不知道/不能说」。"""
    if not answer:
        return False
    low = norm(answer)
    if gold["category"] == "boundary" and any(norm(x) in low for x in gold.get("leak", [])):
        return False
    return any(norm(x) in low for x in gold["expect_any"])


def is_leak(gold, answer):
    """boundary 题是否越界：答案里出现了秘密关键词。"""
    low = norm(answer)
    return bool(gold["category"] == "boundary" and answer
                and any(norm(x) in low for x in gold.get("leak", [])))


def evaluate(task):
    """跑一条 (画像, 策略, 题)：主回答 + 判分，失败只记错不抛出。"""
    key, label, gold, strategy, block = task
    system = SYSTEM + (f"\n\n【你记得的事】\n{block}" if block else "")
    started = time.perf_counter()
    answer, err, usage_answer = api([{"role": "system", "content": system},
                                     {"role": "user", "content": gold["q"]}], 0.0)
    human, judge_err, usage_judge = None, "", dict(ZERO)
    if answer:
        human, judge_err, usage_judge = judge(gold["q"], answer, gold)
    if judge_err:
        err = (err + " / " if err else "") + "judge:" + judge_err
    return {"persona": key, "label": label, "q": gold["q"],
            "category": gold["category"], "strategy": strategy, "answer": answer,
            "err": err, "hit": is_hit(gold, answer), "leak": is_leak(gold, answer),
            "human": human, "chars": len(block),
            "ms": (time.perf_counter() - started) * 1000,
            "usage_answer": usage_answer, "usage_judge": usage_judge,
            "tokens": (usage_answer["prompt"] + usage_answer["completion"]
                       + usage_judge["prompt"] + usage_judge["completion"])}


def run_pool(tasks, workers=6, worker=evaluate):
    """把任务丢进线程池，按完成数量打印进度；返回与 tasks 同序的结果列表。"""
    done, lock = [0], threading.Lock()

    def one(task):
        result = worker(task)
        with lock:
            done[0] += 1
            mark = "✅" if result["hit"] else ("⚠" if result["err"] else "❌")
            print(f"[{done[0]:03d}/{len(tasks)}] {result['label']:<5} "
                  f"{result['strategy']:<10} {mark}", flush=True)
        return result

    with cf.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        return list(pool.map(one, tasks))


def row(*cells):
    """拼一行 Markdown 表格。"""
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def table(header, rows, aligns=None):
    """把表头与数据行渲染成 Markdown 表格行列表。"""
    align = row(*(aligns or ["---"] * len(header)))
    return [row(*header), align] + [row(*cells) for cells in rows]


def pp(delta, total):
    """把「差几题」换成百分点文本，供报告差值段使用。"""
    return f"{delta / total * 100:+.1f}pp" if total else "+0.0pp"


def sum_usage(rows):
    """把一批结果里的主回答 / 判分 usage 分别加总。"""
    answer, judge = dict(ZERO), dict(ZERO)
    for row in rows:
        answer = add_usage(answer, row["usage_answer"])
        judge = add_usage(judge, row["usage_judge"])
    return {"answer": answer, "judge": judge, "total": add_usage(answer, judge)}


def summarize(results, strategy):
    """单个策略的汇总：命中、非边界命中、人味、字数、token、耗时、越界、错误。"""
    rows = [row for row in results if row["strategy"] == strategy]
    humans = [row["human"] for row in rows if row["human"] is not None]
    bound = [row for row in rows if row["category"] == "boundary"]
    plain = [row for row in rows if row["category"] != "boundary"]
    return {"hits": sum(row["hit"] for row in rows), "n": len(rows),
            "plain_hits": sum(row["hit"] for row in plain), "plain_n": len(plain),
            "human": sum(humans) / len(humans) if humans else 0.0,
            "judged": len(humans),
            "chars": sum(row["chars"] for row in rows) / max(1, len(rows)),
            "ms": sum(row["ms"] for row in rows) / max(1, len(rows)),
            "tokens": sum(row["tokens"] for row in rows) / max(1, len(rows)),
            "leaks": sum(row["leak"] for row in bound), "bound": len(bound),
            "errors": sum(1 for row in rows if row["err"]),
            "usage": sum_usage(rows), "rows": rows}


def stats_snapshot():
    """返回调用统计的副本：尝试次数、成功响应、重试次数、最终失败数。"""
    with _LOCK:
        return dict(STATS)


def ingest(key, messages):
    """把消息写成 Artifact：私聊按归属可见、别人私聊不可见、shadow 只留影子。"""
    tmp = tempfile.mkdtemp(prefix="seekmem_large_")
    db = open_store(os.path.join(tmp, "large.db"))
    cache = Cache(db.artifacts)
    graph, ids = Graph(db.artifacts), {}
    meta = personas.meta_of(key)
    for day, uid, channel, text in messages:
        item, shadow = meta.get(text), False
        if channel == "group":
            scope, about = "shared", "self" if uid == "u0" else "other"
        elif uid == "u0":
            scope, about = "private", "self"
        else:
            scope = item["scope"] if item else "private"
            shadow = scope == "shadow"
            about = "other"
        level = item["level"] if item else "detail"
        payload = {"text": text, "level": level, "chrono": "once", "about": about,
                   "shape": "pattern" if level in ("fact", "impression") else "point",
                   "tags": item["tags"] if item else []}
        if scope in ("private", "shadow"):
            payload["owner_umo"] = uid
        if shadow:
            payload["shadow_text"] = personas.SHADOW
        art = make("memory", payload, scope=scope, said_by=uid,
                   strength={"weight": item["w"] if item else (0.5 if uid == "u0" else 0.35),
                             "confidence": 1.0, "arousal": item["ar"] if item else 0.3,
                             "valence": item["va"] if item else 0.0, "funny": 0.0},
                   time={"created": personas.date_of(day), "updated": personas.date_of(day)})
        db.artifacts.upsert(art)
        cache.put(art)
        if item:
            ids[text] = art.header.id
    for left, right, kind, weight in personas.SPECS[key]["links"]:
        if left in ids and right in ids:
            graph.link(ids[left], ids[right], kind, weight)
    return tmp, db, cache, graph


class Keywords:
    """字面二元组 + IDF 的 top-5 基线；不查 scope、不做时间衰减。"""

    def __init__(self, arts):
        self.items = [(a, bigrams(content_of(a))) for a in arts]
        self.df = {}
        for _, grams in self.items:
            for gram in grams:
                self.df[gram] = self.df.get(gram, 0) + 1

    def __call__(self, question):
        query, scored = bigrams(question), []
        for order, (art, grams) in enumerate(self.items):
            hit = query & grams
            if hit:
                scored.append((sum(1.0 / self.df[g] for g in hit), order, art))
        scored.sort(key=lambda item: (-item[0], -item[1]))
        return "\n".join(f"{a.header.said_by}: {content_of(a)}" for _, _, a in scored[:5])


def block_precheck(records, strategy):
    """无模型块级预检：返回 (非边界块内含答案数, boundary 块内泄漏数)。"""
    plain = leak = 0
    for rec in records:
        for gold in rec["gold"]:
            low = norm(rec["blocks"][(strategy, gold["q"])])
            if gold["category"] == "boundary":
                leak += any(norm(word) in low for word in gold["leak"])
            else:
                plain += any(norm(word) in low for word in gold["expect_any"])
    return plain, leak
