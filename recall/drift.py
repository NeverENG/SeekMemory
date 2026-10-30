"""Select existing spontaneous-memory candidates without query scoring or writes.

按既有规则选择偶然浮现记忆，不按查询评分或执行写入。
"""

from __future__ import annotations

import math
import random

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactCache
    from ..core.domain.memory.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactCache
    from core.domain.memory.artifact import Artifact

LEVELS = ("fact", "scene", "detail")
FAMILY = "memory"
BASE_DAYS = 30.0
EMOTION_BONUS = 1.5
MIN_CHANCE = 0.06
MAX_CHANCE = 0.22


def _age_days(created: str, now_days: float) -> float:
    """Compute age using the existing date/ordinal fallback rules / 按既有日期及日序回退规则计算年龄。"""
    try:
        import datetime

        day = datetime.date.fromisoformat(str(created)[:10]).toordinal()
        return max(0.0, float(now_days) - day)
    except (TypeError, ValueError):
        return 0.0


def _today_ordinal() -> float:
    """Read the existing current calendar-day ordinal / 读取既有当前日历日序号。"""
    import datetime

    return float(datetime.date.today().toordinal())


def _in_cooldown(art: Artifact) -> bool:
    """Read the existing used-memory cooldown markers / 读取既有已使用记忆冷却标记。"""
    payload = art.payload if isinstance(art.payload, dict) else {}
    last = payload.get("last_used") or payload.get("hot_until") or payload.get("used_at")
    try:
        hits = int(art.header.strength.hits or 0)
    except (TypeError, ValueError):
        hits = 0
    return bool(hits > 0 and last)


def eligible(art: Artifact) -> bool:
    """Require ordinary nonshadow text, sufficient weight and no existing cooldown / 要求普通非影子正文、足够权重且没有既有冷却。"""
    try:
        if art.header.family != FAMILY:
            return False
        if str(art.header.scope) == "shadow":
            return False
        if str(art.payload.get("level") or "") not in LEVELS:
            return False
        if not str(art.payload.get("text") or "").strip():
            return False
        if _in_cooldown(art):
            return False
        return float(art.header.strength.weight) >= 0.6
    except Exception:  # noqa: BLE001 - Bad rows are ineligible / 坏行不符合条件。
        return False


def candidate(cache: ArtifactCache, now_days: float | None = None) -> list[Artifact]:
    """Read eligible active spontaneous-memory candidates / 读取符合条件的有效偶然浮现候选。"""
    now = _today_ordinal() if now_days is None else float(now_days)
    out: list[Artifact] = []
    try:
        active = list(cache.active())
    except Exception:  # noqa: BLE001 - Unavailable input yields no candidate / 输入不可用时无候选。
        return out
    for art in active:
        if eligible(art):
            out.append(art)
    return out


def _score(art: Artifact, now: float, rng: random.Random) -> float:
    """Weight recency, emotion and importance with the supplied random source / 以给定随机源加权新近程度、情绪及重要性。"""
    strength = art.header.strength
    age = _age_days(str(art.header.time.created or ""), now)
    recency = math.exp(-age / BASE_DAYS)
    emotion = 1.0 + EMOTION_BONUS * float(strength.arousal or 0.0)
    weight = max(0.1, float(strength.weight or 1.0))
    return recency * emotion * weight * (0.5 + rng.random())


def best_of(pool: list[Artifact], seed: int | str | None = None,
            now_days: float | None = None) -> Artifact | None:
    """Choose one eligible supplied memory using existing seeded weighting / 按既有有种子加权选择一条给定可用记忆。"""
    usable = [art for art in pool if eligible(art)]
    if not usable:
        return None
    now = _today_ordinal() if now_days is None else float(now_days)
    rng = random.Random(seed)
    return max(usable, key=lambda art: _score(art, now, rng))


def pick(cache: ArtifactCache, seed: int | str | None = None,
         now_days: float | None = None) -> Artifact | None:
    """Read candidates then choose one spontaneous memory / 读取候选后选择一条偶然浮现记忆。"""
    return best_of(candidate(cache, now_days), seed, now_days)


def should_drift(text: str, seed: int | str | None = None) -> bool:
    """Apply the existing short-chat probability with a seeded random source / 以有种子随机源应用既有短聊天浮现概率。"""
    line = str(text or "").strip()
    rng = random.Random(seed)
    if len(line) > 24:
        return False
    chance = MAX_CHANCE if len(line) <= 8 else MIN_CHANCE
    return rng.random() < chance
