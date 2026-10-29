"""Read active memories, prepare existing decay revisions, atomically commit and update cache.

读取有效记忆，准备既有衰退版本，原子提交后更新缓存。
"""

from __future__ import annotations

import datetime

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, revise
    from ..core.strength import retention
    from .ports import ArtifactCache, ArtifactStore
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, revise
    from core.strength import retention
    from maintain.ports import ArtifactCache, ArtifactStore

from .expiry_policy import FORGET_BELOW, _day, _anchor, decay_plan


def decay_all(artifacts: ArtifactStore, cache: ArtifactCache, today: str) -> int:
    """Compute decay, atomically commit the group, then update cache / 计算衰退并原子提交版本组，再更新缓存。"""
    plan = decay_plan(list(cache.active()), today)
    artifacts.commit_many(plan.rows(), op=plan.op, reason=plan.reason)
    for write in plan.writes:
        cache.remove(write.artifact.header.id)
    return len(plan.writes)
