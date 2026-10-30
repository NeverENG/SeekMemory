"""Construct fixed synthetic fixtures; never open storage or call a model.

构造固定合成样本，不打开存储或调用模型。
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta
import hashlib
import json
import random

from .dataset import build

ANCHOR = date(2026, 10, 30)
CONFIG = {"recall_k": 8, "budget_chars": 600, "explore_rate": 0.0,
          "bm25_enabled": True, "bm25_weight": 1.0, "source_recall_enabled": True}
SESSION = "bot:FriendMessage:owner"


def _rel_time(day: int, today: int = 30) -> dict:
    """Map a sample day to the fixed calendar / 将样本日映射到固定日历。"""
    value = (ANCHOR - timedelta(days=today - day)).isoformat()
    return {"created": value, "updated": value}


def to_artifact(event):
    """Build legacy sample weights; this does not exercise reinforcement.

构造旧样本预设权重，不执行强化。
    """
    from core.artifact import make

    payload = {"text": event.text, "level": event.level, "shape": "point",
               "chrono": "once", "about": "other"}
    if event.tags:
        payload["tags"] = list(event.tags)
    if event.level == "impression":
        payload["shape"] = "pattern"
    identity = hashlib.sha256(f"{event.day}:{event.text}".encode()).hexdigest()[:20]
    return make("memory", payload, id=f"fixture_{identity}",
                strength={"weight": 0.5 + event.importance + 0.1 * (event.mentions - 1),
                          "confidence": 1.0, "arousal": event.arousal,
                          "valence": event.valence, "funny": 0.0}, time=_rel_time(event.day))


def _synthetic_pool(n: int) -> list:
    """Build deterministic scaling samples, including identity and dates / 构造编号和日期也固定的规模样本。"""
    from core.artifact import make

    templates = ("他今天跟我说了{}", "他下午在弄{}", "他提到{}有点麻烦", "他问{}怎么弄", "他{}做完了")
    words = ("项目", "数据库", "接口", "部署", "文档", "测试", "会议", "报表", "脚本", "配置",
             "调度", "缓存", "索引", "图表", "日志", "告警", "备份", "迁移", "权限", "监控")
    rng = random.Random(7)
    return [make("memory", {
        "text": templates[i % len(templates)].format(rng.choice(words) + rng.choice(("", "那部分", "的细节"))) + f"（{i}）",
        "level": "detail", "shape": "point", "chrono": "once", "about": "other",
    }, id=f"scale_{i:05}", time=_rel_time(30)) for i in range(n)]


def corpus_digest() -> str:
    """Hash the unchanged annotations and controlled inputs / 为原标注及受控输入计算指纹。"""
    events, queries = build()
    payload = {"events": [asdict(x) for x in events], "queries": [asdict(x) for x in queries],
               "anchor": ANCHOR.isoformat(), "config": CONFIG}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
