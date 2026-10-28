"""强度算法：艾宾浩斯留存率、衰减权重、强化与命中冷却。

DESIGN 4.3 的公式为 R = e^(-t / S)，
S = 基础 × (1 + 0.5 × 有效命中) × 形状系数 × 情绪系数。
Strength 不单独存 hits，这里用 weight 编码命中：每 +0.1 约等于一次有效命中。
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from math import exp

from .artifact import Strength

# Internal algorithm parameters; these are not user configuration.
BASE_DAYS = 30.0
HIT_STEP = 0.1
COOLDOWN = timedelta(minutes=30)

_HIGH_AROUSAL = 0.7
_LOW_AROUSAL = 0.3
_NEGATIVE_VALENCE = -0.3
_HIGH_AROUSAL_FACTOR = 1.5
_LOW_AROUSAL_FACTOR = 0.8
_NEGATIVE_HIGH_AROUSAL_FACTOR = 1.5
_NEGATIVE_LOW_AROUSAL_FACTOR = 0.6
_MIN_SALIENCE = 0.3
_MAX_SALIENCE = 3.0
_HIT_STABILITY_FACTOR = 0.5

SHAPE_FACTORS: dict[str, float] = {
    "point": 1.0,
    "span": 1.2,
    "pattern": 3.0,
    "rule": 999.0,
}

REINFORCE_DELTAS: dict[str, float] = {
    "recall": 0.1,
    "spoken": 0.3,
    "confirmed": 0.2,
}


def _shape_factor(shape: str) -> float:
    try:
        return SHAPE_FACTORS[shape]
    except KeyError:
        raise ValueError(f"未知 shape：{shape!r}") from None


def _emotion_factor(s: Strength) -> float:
    """情绪系数：高唤醒记得牢，低唤醒忘得快；负效价再叠加创伤/普通不快。"""
    if s.arousal > _HIGH_AROUSAL:
        factor = _HIGH_AROUSAL_FACTOR
    elif s.arousal < _LOW_AROUSAL:
        factor = _LOW_AROUSAL_FACTOR
    else:
        factor = 1.0

    if s.valence < _NEGATIVE_VALENCE:
        if s.arousal > _HIGH_AROUSAL:
            factor *= _NEGATIVE_HIGH_AROUSAL_FACTOR
        elif s.arousal < _LOW_AROUSAL:
            factor *= _NEGATIVE_LOW_AROUSAL_FACTOR
    return factor


def _hits(s: Strength) -> float:
    """有效命中次数。优先用显式 hits；旧数据没有 hits 时用 weight 折算。"""
    if getattr(s, "hits", 0):
        return float(s.hits)
    return max(0.0, (s.weight - 1.0) / HIT_STEP)


def _salience(s: Strength) -> float:
    """显著度：越重要的事基础寿命越长。限制在 [0.3, 3.0] 防止极端值。"""
    return min(_MAX_SALIENCE, max(_MIN_SALIENCE, float(s.weight)))


def retention(s: Strength, shape: str, days: float) -> float:
    """返回留存率 R，取值 [0, 1]；days 为已过去的天数。"""
    elapsed = max(0.0, float(days))
    stability = (
        BASE_DAYS
        * _salience(s)
        * (1.0 + _HIT_STABILITY_FACTOR * _hits(s))
        * _shape_factor(shape)
        * _emotion_factor(s)
    )
    if stability <= 0.0:
        return 0.0
    return exp(-elapsed / stability)


def decayed_weight(s: Strength, shape: str, days: float) -> float:
    """衰减后的权重：原 weight × 留存率（负权重同样按比例淡化）。"""
    return s.weight * retention(s, shape, days)


def reinforce(s: Strength, source: str) -> Strength:
    """按来源强化权重：recall +0.1 / spoken +0.3 / confirmed +0.2。"""
    if source not in REINFORCE_DELTAS:
        allowed = "|".join(REINFORCE_DELTAS)
        raise ValueError(f"未知强化来源：{source!r}，可选：{allowed}")
    delta = REINFORCE_DELTAS[source]
    return replace(s, weight=round(s.weight + delta, 4))


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def hit_cooldown_ok(last_window: str | None, now: str) -> bool:
    """30 分钟冷却：返回 True 表示这次命中可以单独计数。"""
    last, current = _parse(last_window), _parse(now)
    if last is None or current is None:
        return True
    if last.tzinfo is None and current.tzinfo is not None:
        last = last.replace(tzinfo=current.tzinfo)
    elif current.tzinfo is None and last.tzinfo is not None:
        current = current.replace(tzinfo=last.tzinfo)
    return current - last >= COOLDOWN
