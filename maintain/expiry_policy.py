"""Prepare existing decay/expiry revisions without reads or writes.

准备既有衰退及到期版本，不读取外部资源或执行写入；时间和阈值行为不变。
"""
from __future__ import annotations

import datetime
try:
    from ..core.domain.memory.artifact import Artifact, revise
    from ..core.domain.memory.strength import retention
except ImportError:
    from core.domain.memory.artifact import Artifact, revise
    from core.domain.memory.strength import retention
from .plans import RevisionPlan, RevisionWrite

FORGET_BELOW = 0.3


def _day(value: str) -> datetime.date | None:
    """Parse the existing date prefix or return None / 解析既有日期前缀，无效时返回空。"""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _anchor(art: Artifact) -> datetime.date | None:
    """Read last-update date with the existing creation-date fallback / 读取最后更新日期，并保留既有创建日期回退。"""
    span = art.header.time
    return _day(span.updated) or _day(span.created)


def decay_plan(pool: list[Artifact], today: str) -> RevisionPlan:
    """Prepare one atomic forgotten group using the existing retention curve / 按既有留存曲线准备一个原子遗忘版本组。"""
    base = _day(today)
    if base is None:
        return RevisionPlan((), "forget", "retention decay")
    expired = []
    for art in pool:
        if art.header.family != "memory":
            continue
        anchor = _anchor(art)
        if anchor is None:
            continue
        days = max((base - anchor).days, 0)
        level = str(art.payload.get("level") or "")
        if level == "fact":
            continue
        shape = str(art.payload.get("shape") or "point")
        if retention(art.header.strength, shape, float(days)) >= FORGET_BELOW:
            continue
        expired.append(art)
    if not expired:
        return RevisionPlan((), "forget", "retention decay")
    return RevisionPlan(tuple(
        RevisionWrite(revise(art, state="forgotten"), art.header.revision, tuple(art.header.lineage.sources))
        for art in expired
    ), "forget", "retention decay")

def _date(value: str | None) -> datetime.date | None:
    """Parse the existing date prefix or return None / 解析既有日期前缀，无效时返回空。"""
    if not isinstance(value, str) or len(value) < 10:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


def _expired(art: Artifact, today: datetime.date) -> bool:
    """Compare existing expiry/valid-to dates to the supplied day / 将既有过期及有效截止日期与给定日比较。"""
    deadline = _date(art.header.time.expires) or _date(art.header.time.valid_to)
    return deadline is not None and deadline < today


def expiry_plan(pool: list[Artifact], today: str = "") -> RevisionPlan:
    """Prepare one atomic forgotten group using existing expiry dates / 按既有到期日期准备一个原子遗忘版本组。"""
    try:
        base = datetime.date.fromisoformat(today[:10]) if today else datetime.date.today()
    except ValueError:
        base = datetime.date.today()
    expired = [art for art in pool if _expired(art, base)]
    if not expired:
        return RevisionPlan((), "forget", "lifecycle expiration")
    return RevisionPlan(tuple(
        RevisionWrite(revise(art, state="forgotten"), art.header.revision, tuple(art.header.lineage.sources))
        for art in expired
    ), "forget", "lifecycle expiration")
