"""群聊仿真数据与基线策略。

被 scale.py（离线规模测试）和 e2e.py（端到端模型评测）共用。
"""

from __future__ import annotations

import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.domain.memory.artifact import content_of, make  # noqa: E402

USERS = int(os.environ.get("SCALE_USERS", "8"))
DAYS = int(os.environ.get("SCALE_DAYS", "60"))
MSGS_PER_DAY = int(os.environ.get("SCALE_MSGS", "40"))

# 摘要基线：每天压一句，只保留最近 7 天
SUMMARY_DAYS = 7
SUMMARY_CHARS = 40

# 噪声词表刻意避开查询关键词，模拟"无关闲聊"
TOPICS = ["项目", "数据库", "接口", "部署", "文档", "测试", "会议", "报表",
          "脚本", "配置", "调度", "缓存", "索引", "图表", "日志", "告警",
          "备份", "迁移", "权限", "监控"]
VERBS = ["今天在弄", "说{}有点烦", "问{}怎么搞", "把{}改完了", "吐槽{}太慢"]
# 事实标签：从文本主题自然派生（与生产 perceive/extract 的输出同构）。
FACT_TAGS = (
    ("吕宇轩", ("名字", "称呼")),
    ("量化", ("工作", "项目")),
    ("架构师", ("职业", "目标")),
    ("面试", ("面试", "工作")),
    ("加班", ("加班", "工作")),
    ("睡不着", ("睡眠", "情绪")),
    ("领导", ("情绪", "心情", "工作")),
    ("倔", ("印象", "性格")),
    ("照顾自己", ("印象", "自理")),
)
NOISE_TAGS = ("日常",)
OWNER_FACTS = [
    "我叫吕宇轩，也叫 BangBang",
    "我在做量化交易项目",
    "我想成为核心架构师",
    "我面试了万兴科技",
    "我面试过了",
    "我加班到两点",
    "我最近睡不着",
    "我被领导骂了",
    "我有点倔，但真有事会帮",
    "我不会照顾自己，经常忘记吃饭",
]


def gen_messages(seed: int = 7):
    """生成 (day, uid, text) 列表。"""
    rng = random.Random(seed)
    out = []
    for day in range(1, DAYS + 1):
        for i in range(MSGS_PER_DAY):
            uid = rng.randrange(USERS)
            if uid == 0 and i < len(OWNER_FACTS):
                text = OWNER_FACTS[i]
            else:
                text = f"{rng.choice(['他', '我', '你'])}{rng.choice(VERBS).format(rng.choice(TOPICS))}{rng.randrange(100)}"
            out.append((day, uid, text))
    return out


def tags_of(text: str, owner: bool) -> list[str]:
    """从文本主题派生标签；取不到主题时按日常闲聊处理。"""
    if not owner:
        return list(NOISE_TAGS)
    tags: list[str] = []
    for key, labels in FACT_TAGS:
        if key in text:
            tags.extend(label for label in labels if label not in tags)
    return tags or list(NOISE_TAGS)


def to_art(day: int, uid: int, text: str):
    level = "scene" if uid == 0 else "detail"
    if uid == 0 and any(k in text for k in ("我叫", "我在做", "我想成为")):
        level = "fact"
    return make(
        "memory",
        {"text": text, "level": level, "shape": "point", "chrono": "once",
         "about": "other", "tags": tags_of(text, uid == 0)},
        scope="private" if uid == 0 else "shadow",
        strength={"weight": 2.0 if text in OWNER_FACTS else 0.6,
                  "confidence": 1.0 if uid == 0 else 0.7,
                  "arousal": 0.4, "valence": 0.0, "funny": 0.0},
        time={"created": f"2026-{(day // 28) + 7:02d}-{(day % 28) + 1:02d}",
              "updated": f"2026-{(day // 28) + 7:02d}-{(day % 28) + 1:02d}"},
    )


def baseline_window(pool, k=20):
    """朴素滑窗：最近 k 条全塞。"""
    return pool[-k:]


def baseline_keyword(pool, q, k=8):
    """朴素关键词匹配：谁包含 query 里最长的词就取谁。"""
    tokens = [t for t in ("面试", "加班", "量化", "架构师", "睡不着", "领导", "吕宇轩") if t in q]
    if not tokens:
        return pool[-k:]
    hit = [a for a in pool if any(t in content_of(a) for t in tokens)]
    return hit[:k]


def baseline_full(pool):
    return pool


def _tf(text: str) -> dict[str, float]:
    """字符二元组词频向量；标点与空白不参与。"""
    chars = [c.lower() for c in str(text) if c.isalnum()]
    vec: dict[str, float] = {}
    for i in range(len(chars) - 1):
        gram = chars[i] + chars[i + 1]
        vec[gram] = vec.get(gram, 0.0) + 1.0
    return vec


def _norm(vec: dict[str, float]) -> float:
    return math.sqrt(sum(value * value for value in vec.values()))


def build_vector_index(pool) -> dict[str, tuple[dict[str, float], float]]:
    """预计算每条记忆的 TF 向量与模长，检索时不再重算。"""
    index: dict[str, tuple[dict[str, float], float]] = {}
    for art in pool:
        vec = _tf(content_of(art))
        index[art.header.id] = (vec, _norm(vec))
    return index


def baseline_vector(pool, q, k=8, index=None):
    """伪向量检索：字符二元组 TF + 余弦相似度取 top-k；零重合时不返回。"""
    if index is None:
        index = build_vector_index(pool)
    query = _tf(q)
    q_norm = _norm(query)
    if not query or q_norm <= 0.0:
        return []
    scored = []
    for art in pool:
        item = index.get(art.header.id)
        if item is None:
            continue
        vec, norm = item
        if not vec or norm <= 0.0:
            continue
        # 只在较短的一侧迭代，减少 Python 字典查找次数
        if len(query) <= len(vec):
            dot = sum(w * vec.get(gram, 0.0) for gram, w in query.items())
        else:
            dot = sum(w * query.get(gram, 0.0) for gram, w in vec.items())
        if dot > 0.0:
            scored.append((dot / (q_norm * norm), art.header.id, art))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [art for _, _, art in scored[:k]]


def build_daily_summaries(msgs, limit: int = SUMMARY_CHARS) -> dict[int, str]:
    """把每天全部用户（含 shadow）的消息按顺序拼成一句，截到 limit 字。"""
    buckets: dict[int, list[str]] = {}
    for day, _uid, text in msgs:
        buckets.setdefault(day, []).append(str(text))
    out: dict[int, str] = {}
    for day, texts in buckets.items():
        raw = "；".join(texts)
        out[day] = raw if len(raw) <= limit else raw[: limit - 1].rstrip("；，、 ") + "…"
    return out


def baseline_summary(summaries, days: int = SUMMARY_DAYS):
    """检索时只返回最近 days 天的摘要。"""
    recent = sorted(summaries)[-days:]
    return [summaries[day] for day in recent]


def _texts(picked) -> list[str]:
    """基线可以返回 Artifact，也可以直接返回文本。"""
    return [item if isinstance(item, str) else content_of(item) for item in picked]


def _fmt_ms(ms: float) -> str:
    """小于 0.01ms 时不显示成 0.00，避免看起来像没测。"""
    return f"{ms:.2f}ms" if ms >= 0.01 else "<0.01ms"


def _snip(text: str, needle: str, width: int = 28) -> str:
    """截取注入片段；命中时把关键词放进可见窗口，便于核对。"""
    text = " ".join(text.replace("|", "/").split())
    pos = text.find(needle) if needle else -1
    start = max(0, pos - width // 3) if pos >= 0 else 0
    piece = text[start:start + width]
    if not piece:
        return "—"
    return ("…" if start > 0 else "") + piece + ("…" if start + width < len(text) else "")


