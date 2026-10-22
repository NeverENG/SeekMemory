"""recall.score：给单条记忆打分，并按分数与探索率选出注入集合。

打分复用 recall.seed 缓存的二元组 / 标签，消息侧的二元组、情绪词计数
与文本小写形式按 text 缓存，日期新鲜度按 created 在单次 select 内复用；
select 走批量打分（省掉逐条函数调用与重复取数），排序与探索逻辑不变。
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from datetime import date

try:  # 作为 astrbot 插件包的一部分导入
    from ..core.artifact import Artifact
    from ..core.retrieval import RetrievalCandidate
    from . import gate as gate_mod
    from .seed import bigrams, dice, signals_of
except ImportError:  # 作为顶层 recall 包导入（脚本 / 测试）
    from core.artifact import Artifact
    from core.retrieval import RetrievalCandidate
    from recall import gate as gate_mod
    from recall.seed import bigrams, dice, signals_of

POSITIVE = ("开心", "高兴", "喜欢", "哈哈", "笑", "好玩", "可爱", "棒")
NEGATIVE = ("累", "烦", "难过", "委屈", "生气", "难受", "哭", "焦虑", "压力", "孤单", "怕")
ABS_DAYS = 10_000
ORDINAL_DAYS = 500_000
EPOCH_ORDINAL = date(1970, 1, 1).toordinal()

# 相关性闸门（Recall Gate）只认证据，阈值与常量见 recall.gate。

TEXT_CACHE_LIMIT = 16
STATIC_CACHE_LIMIT = 20_000
FRESH_CACHE_LIMIT = 4096
_TEXT_CACHE: OrderedDict[str, tuple[frozenset[str], int, str, int, int, bool]] = OrderedDict()
_STATIC_CACHE: OrderedDict[int, tuple] = OrderedDict()
_FRESH_CACHE: OrderedDict[tuple[str, float], float] = OrderedDict()


def _text_stats(text: str) -> tuple[frozenset[str], int, str, int, int, bool]:
    """消息侧只算一次：二元组、小写、正负情绪词数、是否在笑。"""
    cached = _TEXT_CACHE.get(text)
    if cached is not None:
        _TEXT_CACHE.move_to_end(text)
        return cached
    grams = frozenset(bigrams(text))
    stats = (
        grams,
        len(grams),
        text.lower(),
        sum(text.count(word) for word in POSITIVE),
        sum(text.count(word) for word in NEGATIVE),
        "哈哈" in text or "笑" in text,
    )
    _TEXT_CACHE[text] = stats
    if len(_TEXT_CACHE) > TEXT_CACHE_LIMIT:
        _TEXT_CACHE.popitem(last=False)
    return stats


def _tag_match(low: str, grams: frozenset[str], total: int,
               tags: tuple[str, ...]) -> float:
    """标签命中比例，0~1；标签越少，单条命中越值钱。"""
    if not tags:
        return 0.0
    hits = sum(
        1 for tag in tags
        if tag in low or dice(grams, total, frozenset(bigrams(tag))) >= 0.5
    )
    return min(1.0, hits / len(tags))


def _emotion_match(pos: int, neg: int, smile: bool, strength: object) -> float:
    """消息情绪与记忆强度/效价的贴合度，0~1。"""
    arousal = max(0.0, min(1.0, strength.arousal))
    if not pos and not neg:
        return 0.3 * arousal
    polarity = 1 if pos > neg else -1 if neg > pos else 0
    if polarity == 0 or abs(strength.valence) < 1e-9:
        align = 0.6
    elif polarity * strength.valence > 0:
        align = 1.0
    else:
        align = 0.2
    funny = 0.2 if strength.funny > 0.5 and smile else 0.0
    return min(1.0, align * (0.4 + 0.6 * arousal) + funny)


def _emotion_value(pos: int, neg: int, smile: bool, arousal: float,
                   valence: float, funny: float) -> float:
    """_emotion_match 的批量版本：素材已从静态缓存取出。"""
    if not pos and not neg:
        return 0.3 * arousal
    polarity = 1 if pos > neg else -1 if neg > pos else 0
    if polarity == 0 or abs(valence) < 1e-9:
        align = 0.6
    elif polarity * valence > 0:
        align = 1.0
    else:
        align = 0.2
    bonus = 0.2 if funny > 0.5 and smile else 0.0
    return min(1.0, align * (0.4 + 0.6 * arousal) + bonus)


def _age_days(created: str, now_days: float) -> float:
    """把 now_days 归一成距今天数：0 用 created 算，正小数视为年龄，大数视为绝对天数。"""
    if 0 < now_days < ABS_DAYS:
        return float(now_days)
    try:
        day = date.fromisoformat(str(created)[:10])
    except (TypeError, ValueError):
        return max(0.0, float(now_days)) if now_days < ABS_DAYS else 0.0
    if now_days == 0:
        return max(0.0, (date.today() - day).days)
    base = day.toordinal() if now_days > ORDINAL_DAYS else day.toordinal() - EPOCH_ORDINAL
    return max(0.0, now_days - base)


def _freshness(created: str, now_days: float) -> float:
    """指数新鲜度：当天 1.0，约两周衰减到 0.37；按日期复用结果。"""
    key = (created, now_days)
    cached = _FRESH_CACHE.get(key)
    if cached is not None:
        _FRESH_CACHE.move_to_end(key)
        return cached
    value = math.exp(-_age_days(created, now_days) / 14.0)
    _FRESH_CACHE[key] = value
    if len(_FRESH_CACHE) > FRESH_CACHE_LIMIT:
        _FRESH_CACHE.popitem(last=False)
    return value


def _recently_used(art: Artifact) -> float:
    """最近刚用过返回 1.0，用于 -2.0 惩罚；命中数以 header.strength 为准。"""
    try:
        hits = int(art.header.strength.hits)
    except (TypeError, ValueError):
        hits = 0
    payload = art.payload
    last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
    return 1.0 if hits > 0 and last else 0.0


def _static(art: Artifact) -> tuple:
    """与消息无关的打分素材，按对象身份缓存，供 score / select 复用。"""
    key = id(art)
    cached = _STATIC_CACHE.get(key)
    if cached is not None:
        return cached
    grams, tags = signals_of(art)
    strength = art.header.strength
    entry = (
        art, grams, tags, strength.weight,
        max(0.0, min(1.0, strength.arousal)), strength.valence, strength.funny,
        art.header.time.created, _recently_used(art),
    )
    _STATIC_CACHE[key] = entry
    if len(_STATIC_CACHE) > STATIC_CACHE_LIMIT:
        _STATIC_CACHE.popitem(last=False)
    return entry


def score(art: Artifact, text: str, activation: float, now_days: float) -> float:
    """
    单条记忆的综合分（DESIGN 5.1）。

    3.0×字面 + 2.0×标签 + 1.5×情绪 + 1.0×weight
    + 0.5×新鲜度 + 1.5×激活 − 2.0×刚用过。
    """
    _, grams, tags, weight, arousal, valence, funny, created, recent = _static(art)
    text_grams, total, low, pos, neg, smile = _text_stats(text)
    return (
        3.0 * dice(text_grams, total, grams)
        + 2.0 * _tag_match(low, text_grams, total, tags)
        + 1.5 * _emotion_value(pos, neg, smile, arousal, valence, funny)
        + 1.0 * weight
        + 0.5 * _freshness(created, now_days)
        + 1.5 * max(0.0, activation)
        - 2.0 * recent
    )


def select(
    candidates: list[Artifact] | list[tuple[Artifact, float]] | list[RetrievalCandidate],
    text: str,
    now_days: float,
    k: int = 8,
    explore: float = 0.1,
    seed: int | str | None = None,
    gate: bool = True,
    min_ev_abs: float | None = None,
    min_ev_rel: float | None = None,
    lexical_weight: float = 2.0,
) -> list[Artifact]:
    """
    按分数取 top-k，并以 explore 概率随机捞一条非 top 的记忆做探索。

    candidates 兼容裸 Artifact 与 (Artifact, activation) 二元组；seed
    固定即可复现，不传时用 text 当种子，保证同一条消息选出同一批。

    gate=True 时先过证据闸门（ISSUE-0017）：只有字面、标签、激活、情绪
    四项累计的 evidence 达到 max(绝对下限, top_evidence × 相对下限) 的候选
    才注入；weight / freshness / recent 只参与排序。没有候选达标、或消息
    是纯问时间的时钟类问题，都返回 []（不相关就不注入）。
    gate=False 保持旧行为（永远尽量凑满 k），供消融实验对比。
    min_ev_abs / min_ev_rel 用来覆盖 recall.gate 的默认证据阈值（配置/标定）。
    """
    if k <= 0 or not candidates:
        return []
    if not math.isfinite(lexical_weight):
        raise ValueError("lexical_weight 必须是有限数值")
    if gate and gate_mod.is_clock_query(text):
        return []
    pairs = []
    for item in candidates:
        if isinstance(item, RetrievalCandidate):
            pairs.append((item.artifact, item.activation, item.lexical))
        elif isinstance(item, tuple):
            pairs.append((item[0], item[1] if len(item) > 1 else 0.0, 0.0))
        else:
            pairs.append((item, 0.0, 0.0))
    text_grams, total, low, pos, neg, smile = _text_stats(text)
    plain = not pos and not neg
    polarity = 0 if plain else (1 if pos > neg else -1 if neg > pos else 0)
    fresh: dict[str, float] = {}
    scored: list[tuple[float, str, int, Artifact, float]] = []
    append = scored.append
    cache = _STATIC_CACHE
    for order, (art, act, lexical) in enumerate(pairs):
        entry = cache.get(id(art))
        if entry is None:
            entry = _static(art)
        _, grams, tags, weight, arousal, valence, funny, created, recent = entry
        value = 0.0
        evidence = 0.0
        if total and grams:
            inter = 0
            for gram in text_grams:
                if gram in grams:
                    inter += 1
            if inter:
                literal = 3.0 * (2.0 * inter / (total + len(grams)))
                value += literal
                evidence += literal
        if lexical > 0:
            lexical_score = max(0.0, float(lexical_weight)) * max(
                0.0, min(1.0, float(lexical))
            )
            value += lexical_score
            evidence += lexical_score
        if tags:
            tag_hit = 2.0 * _tag_match(low, text_grams, total, tags)
            value += tag_hit
            evidence += tag_hit
        if plain:
            emotion = 1.5 * (0.3 * arousal)
        else:
            if polarity == 0 or abs(valence) < 1e-9:
                align = 0.6
            elif polarity * valence > 0:
                align = 1.0
            else:
                align = 0.2
            bonus = 0.2 if funny > 0.5 and smile else 0.0
            emotion = 1.5 * min(1.0, align * (0.4 + 0.6 * arousal) + bonus)
        value += emotion
        evidence += emotion
        value += weight
        age = fresh.get(created)
        if age is None:
            age = math.exp(-_age_days(created, now_days) / 14.0)
            fresh[created] = age
        value += 0.5 * age
        activation = 1.5 * max(0.0, float(act))
        value += activation
        evidence += activation
        value -= 2.0 * recent
        append((-value, art.header.id, order, art, evidence))
    scored.sort()
    if gate:
        if not scored:
            return []
        top_evidence = max(item[4] for item in scored)
        floor = gate_mod.evidence_floor(top_evidence, min_ev_abs, min_ev_rel)
        scored = [item for item in scored if item[4] >= floor]
        if not scored:
            return []
    top = [item[3] for item in scored[:k]]
    rest = scored[k:]
    if rest and 0.0 < explore <= 1.0:
        rng = random.Random(seed if seed is not None else text)
        if rng.random() < explore:
            pick = rng.choice(rest)[3]
            top = (top[:-1] + [pick]) if len(top) >= k else top + [pick]
    return top
