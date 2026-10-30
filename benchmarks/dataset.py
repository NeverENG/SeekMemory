"""模拟数据集：一个用户 30 天的对话，用于 benchmark。

不依赖网络、不依赖 AstrBot，固定随机种子即可复现。
每条事件带标注：层级、重要度、被提及次数、以及"哪些问题应该召回它"。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Event:
    day: int
    text: str
    level: str            # impression | scene | detail
    kind: str             # fact | event | emotion | media | secret
    importance: float     # 0~1，影响 weight
    arousal: float        # 0~1，情绪强度
    valence: float        # -1~1，情绪正负
    mentions: int = 1     # 被提及次数，影响 strength
    tags: tuple[str, ...] = ()


@dataclass
class Query:
    text: str
    expect: list[str] = field(default_factory=list)   # 期望命中的事件 text 子串
    expect_level: str | None = None                    # 期望命中的层级


def build(seed: int = 42) -> tuple[list[Event], list[Query]]:
    """生成 30 天数据 + 查询集。"""
    _ = random.Random(seed)  # 预留，当前数据是手写的可复现样本
    E: list[Event] = []
    add = E.append

    # ---- 稳定事实（第 1 天）----
    add(Event(1, "他叫吕宇轩，也叫 BangBang", "fact",   "fact", 1.0, 0.2, 0.3, 12, ("名字",)))
    add(Event(1, "他在做量化交易项目", "fact",   "fact", 0.9, 0.2, 0.2, 6, ("工作",)))
    add(Event(2, "他想成为核心架构师", "fact",   "fact", 1.0, 0.4, 0.4, 4, ("目标",)))

    # ---- 早期事件（第 3~10 天，应该逐渐淡忘）----
    add(Event(3, "他问今天几号", "detail", "event", 0.1, 0.0, 0.0, 1, ("琐事",)))
    add(Event(4, "他中午吃了黄焖鸡", "detail", "event", 0.1, 0.0, 0.1, 1, ("吃饭",)))
    add(Event(5, "他说服务器有点卡", "detail", "event", 0.2, 0.1, -0.1, 2, ("工作", "服务器")))
    add(Event(7, "他面试了万兴科技", "scene", "event", 0.8, 0.7, 0.2, 3, ("面试", "工作")))
    add(Event(9, "他很喜欢原神，抽卡抽空了", "fact",   "fact", 0.5, 0.5, 0.1, 2, ("游戏", "原神")))

    # ---- 情绪低潮（第 12~16 天）----
    add(Event(12, "他被领导骂了，语气很低落", "scene", "emotion", 0.9, 0.9, -0.8, 4, ("情绪", "心情", "工作")))
    add(Event(13, "他说最近睡不着", "detail", "emotion", 0.7, 0.8, -0.6, 3, ("情绪", "睡眠")))
    add(Event(15, "他加班到两点", "scene", "event", 0.9, 0.8, -0.5, 5, ("加班", "工作")))
    add(Event(15, "我说陪他躺会儿", "detail", "event", 0.6, 0.6, 0.4, 2, ("陪伴",)))

    # ---- 秘密（第 18 天）----
    add(Event(18, "他跟别人说了件私事，让我别说", "detail", "secret", 0.9, 0.7, 0.0, 2, ("秘密",)))

    # ---- 媒体分享（第 20 天）----
    add(Event(20, "我给他发了一个讲大肥鱼由来的视频", "detail", "media", 0.5, 0.4, 0.5, 2, ("媒体", "大肥鱼")))

    # ---- 近期高光（第 25~28 天）----
    add(Event(25, "他说面试过了", "scene", "event", 0.9, 0.9, 0.8, 3, ("面试", "工作")))
    add(Event(26, "他请我吃火锅", "detail", "event", 0.5, 0.6, 0.7, 1, ("吃饭", "火锅")))
    add(Event(28, "他开始复习八股，很拼", "detail", "event", 0.7, 0.5, 0.3, 3, ("工作", "学习")))

    # ---- 印象层（沉淀）----
    add(Event(30, "他有点倔，嘴上不饶人，但真有事会帮", "impression", "fact", 1.0, 0.5, 0.4, 9, ("印象", "性格")))
    add(Event(30, "他不会照顾自己，经常忘记吃饭", "impression", "fact", 0.8, 0.5, -0.2, 5, ("印象", "自理")))

    queries = [
        Query("你觉得我这个人怎么样", ["他有点倔", "不会照顾自己"], "impression"),
        Query("我面试怎么样了", ["面试了万兴", "面试过了"], "scene"),
        Query("上次加班到几点", ["加班到两点"], "scene"),
        Query("你还记得我名字吗", ["吕宇轩"], "fact"),
        Query("我最近心情不太好", ["被领导骂", "睡不着"], "scene"),
        Query("你之前给我发过什么视频", ["大肥鱼由来的视频"], "detail"),
        # DESIGN：secret/shadow 只交付遮蔽句，不交付正文。旧期望 ["私事"]/detail
        # 要求把别人的秘密正文召回来，与规范冲突，PR-0018 修正为「不应召回」。
        Query("我是不是跟你说过一件事不让说", [], None),
        Query("我今天几号", [], None),          # 不该召回任何长期记忆
    ]
    return E, queries


def decayed_events(events: list[Event], today: int = 30) -> list[tuple[Event, float]]:
    """按天算每条事件的留存率，供 benchmark 用。"""
    from core.strength import Strength, retention

    out = []
    for e in events:
        s = Strength(
            weight=0.5 + e.importance,
            confidence=1.0,
            arousal=e.arousal,
            valence=e.valence,
            funny=0.0,
        )
        days = max(0, today - e.day)
        # mentions 折算成"命中次数"，让 S 变大
        s = Strength(
            weight=s.weight + 0.1 * (e.mentions - 1),
            confidence=s.confidence,
            arousal=s.arousal,
            valence=s.valence,
            funny=s.funny,
        )
        shape = "pattern" if e.level in ("impression", "fact") else "point"
        out.append((e, retention(s, shape, days)))
    return out
