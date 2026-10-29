"""Read active memories, prepare expiry revisions, atomically commit and update cache.

读取有效记忆，准备到期版本，原子提交后更新缓存。
"""

from __future__ import annotations

import datetime

try:
    from ..core.artifact import Artifact, revise
    from .ports import ArtifactCache, ArtifactStore
except ImportError:
    from core.artifact import Artifact, revise
    from maintain.ports import ArtifactCache, ArtifactStore


from .expiry_policy import _date, _expired, expiry_plan


def forget_expired(artifacts: ArtifactStore, cache: ArtifactCache, today: str = "") -> int:
    """Compute expiry, atomically commit the group, then update cache / 计算到期并原子提交版本组，再更新缓存。"""
    plan = expiry_plan(list(cache.active()), today)
    artifacts.commit_many(plan.rows(), op=plan.op, reason=plan.reason)
    for write in plan.writes:
        cache.remove(write.artifact.header.id)
    return len(plan.writes)
