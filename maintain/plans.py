"""Prepared immutable maintenance revisions; no persistence or resource ownership.

已准备的不可变维护版本，不持久化或管理资源。
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from ..core.artifact import Artifact
except ImportError:
    from core.artifact import Artifact


@dataclass(frozen=True)
class RevisionWrite:
    """One observed head and prepared replacement / 一个观察到的当前版本及已准备替换版本。"""

    artifact: Artifact
    expected_revision: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class RevisionPlan:
    """An atomic revision group; distinct plans are not one transaction.

    一个原子版本组，不同计划之间不是整体事务。
    """

    writes: tuple[RevisionWrite, ...]
    op: str
    reason: str

    def rows(self) -> list[tuple[Artifact, int, tuple[str, ...]]]:
        """Adapt to the existing group-commit shape / 转换为既有分组提交形式。"""
        return [(write.artifact, write.expected_revision, write.source_ids) for write in self.writes]
