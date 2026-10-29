"""Score and select supplied candidates using bounded derived caches and existing formulas.

按有界派生缓存及既有公式评分和选择给定候选，不写入业务状态。
"""

from __future__ import annotations

import math
import random
from collections import OrderedDict
from datetime import date

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact
    from ..core.retrieval import RetrievalCandidate
    from . import gate as gate_mod
    from .seed import bigrams, dice, signals_of
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact
    from core.retrieval import RetrievalCandidate
    from recall import gate as gate_mod
    from recall.seed import bigrams, dice, signals_of

POSITIVE = ("开心", "高兴", "喜欢", "哈哈", "笑", "好玩", "可爱", "棒")
NEGATIVE = ("累", "烦", "难过", "委屈", "生气", "难受", "哭", "焦虑", "压力", "孤单", "怕")
ABS_DAYS = 10_000
ORDINAL_DAYS = 500_000
EPOCH_ORDINAL = date(1970, 1, 1).toordinal()

# Evidence gate thresholds belong to recall.gate / 证据条件阈值归 recall.gate 管理。

TEXT_CACHE_LIMIT = 16
STATIC_CACHE_LIMIT = 20_000
FRESH_CACHE_LIMIT = 4096
_TEXT_CACHE: OrderedDict[str, tuple[frozenset[str], int, str, int, int, bool]] = OrderedDict()
_STATIC_CACHE: OrderedDict[int, tuple] = OrderedDict()
_FRESH_CACHE: OrderedDict[tuple[str, float], float] = OrderedDict()


def _text_stats(text: str) -> tuple[frozenset[str], int, str, int, int, bool]:
    """Cache query grams, case and emotion signals once per text / 每个文本只缓存一次查询二元组、大小写及情绪信号。"""
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
    """Compute the existing normalized tag-hit proportion / 计算既有规范标签命中比例。"""
    if not tags:
        return 0.0
    hits = sum(
        1 for tag in tags
        if tag in low or dice(grams, total, frozenset(bigrams(tag))) >= 0.5
    )
    return min(1.0, hits / len(tags))


def _emotion_match(pos: int, neg: int, smile: bool, strength: object) -> float:
    """Compute bounded query and memory emotion alignment / 计算有上限的查询及记忆情绪贴合度。"""
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
    """Compute existing emotion alignment from precomputed values / 根据预计算值计算既有情绪贴合度。"""
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
    """Compute age using the existing date/ordinal fallback rules / 按既有日期及日序回退规则计算年龄。"""
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
    """Compute and cache existing exponential date freshness / 计算并缓存既有指数日期新鲜度。"""
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
    """Read used markers and strength hits for the existing penalty / 读取已用标记及强度命中次数以计算既有惩罚。"""
    try:
        hits = int(art.header.strength.hits)
    except (TypeError, ValueError):
        hits = 0
    payload = art.payload
    last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
    return 1.0 if hits > 0 and last else 0.0


def _static(art: Artifact) -> tuple:
    """Cache immutable per-object scoring signals with a bound / 按对象缓存不变评分信号，并限制数量。"""
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
    """Combine existing lexical, tag, emotion, strength, age and activation weights / 组合既有字面、标签、情绪、强度、年龄及激活权重。"""
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
    diagnostics: dict | None = None,
) -> list[Artifact]:
    """Apply evidence gates, rank top-k and optional seeded exploration / 应用证据条件、选择最高前 k 项并可进行有种子探索。"""
    if diagnostics is not None:
        diagnostics.update(evaluated=False, passed=0, rejected=0, threshold=0.0)
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
        if diagnostics is not None:
            passed = sum(item[4] >= floor for item in scored)
            diagnostics.update(evaluated=True, passed=passed,
                               rejected=len(scored) - passed, threshold=floor)
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
