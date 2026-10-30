"""Compute retention, decay, reinforcement and hit cooldown without I/O. Explicit hits take priority; legacy weights supply a fallback hit estimate.

计算留存、衰减、强化及命中冷却，不读写资源。显式命中优先，旧权重提供命中估算回退。
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
    """Compute the existing arousal/negative-valence stability factor.

    计算既有唤醒度及负效价稳定系数。
    """
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
    """Prefer explicit hits and estimate legacy hits from weight when absent.

    优先使用显式命中，缺少时由旧权重估算。
    """
    if getattr(s, "hits", 0):
        return float(s.hits)
    return max(0.0, (s.weight - 1.0) / HIT_STEP)


def _salience(s: Strength) -> float:
    """Bound weight-based salience to the existing stability range.

    将基于权重的显著度限制在既有稳定范围。
    """
    return min(_MAX_SALIENCE, max(_MIN_SALIENCE, float(s.weight)))


def retention(s: Strength, shape: str, days: float) -> float:
    """Return retention in [0, 1] for elapsed days and the supplied shape.

    根据已过天数及给定形状返回 [0, 1] 内留存率。
    """
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
    """Multiply the original weight by retention, including negative weights.

    将原权重乘以留存率，负权重同样适用。
    """
    return s.weight * retention(s, shape, days)


def reinforce(s: Strength, source: str) -> Strength:
    """Return new strength with recall +0.1, spoken +0.3 or confirmed +0.2; no persistence.

    返回新强度，recall 增加 0.1、spoken 增加 0.3、confirmed 增加 0.2，不执行保存。
    """
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
    """Allow a separately counted hit outside the existing thirty-minute cooldown.

    在既有三十分钟冷却外允许单独计数命中。
    """
    last, current = _parse(last_window), _parse(now)
    if last is None or current is None:
        return True
    if last.tzinfo is None and current.tzinfo is not None:
        last = last.replace(tzinfo=current.tzinfo)
    elif current.tzinfo is None and last.tzinfo is not None:
        current = current.replace(tzinfo=last.tzinfo)
    return current - last >= COOLDOWN
