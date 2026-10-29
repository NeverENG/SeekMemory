"""Validate sequential Artifact revisions and describe state events without persistence.

校验连续 Artifact 版本并描述状态事件，不执行保存。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .artifact import Artifact

OPS = ("create", "revise", "reinforce", "deliver", "merge", "forget", "promote")
CHECKPOINT_OPS = ("reinforce", "deliver", "promote")


class VersionError(ValueError):
    """Report identity, sequence or version invariant violations.

    报告编号、顺序或版本不变量违规。
    """
    pass


@dataclass(frozen=True)
class StateEvent:
    """Describe an observed revision and an operation delta for atomic commit.

    描述已观察版本及用于原子提交的操作增量。
    """
    id: str
    entity_id: str
    revision_seen: int
    op: str
    delta: dict[str, Any] = field(default_factory=dict)
    at: str = ""

    def validate(self) -> None:
        """Validate event identity, observed revision and dictionary delta.

        校验事件编号、已观察版本及字典增量。
        """
        if not self.id or not self.entity_id:
            raise ValueError("state event needs id and entity_id")
        if self.revision_seen < 1:
            raise ValueError("revision_seen must be >= 1")
        if not isinstance(self.delta, dict):
            raise ValueError("delta must be a dict")


def assert_next_revision(previous: Artifact | None, current: Artifact) -> None:
    """Require stable identity/family/creation time and the exact next revision; raise VersionError on mismatch.

    要求编号、类别及创建时间稳定且版本恰好连续，不符则抛出 VersionError。
    """
    if current.header.revision < 1:
        raise VersionError("revision must start at 1")
    if previous is None:
        if current.header.revision != 1:
            raise VersionError("new artifact revision must be 1")
        return
    if current.header.id != previous.header.id:
        raise VersionError("artifact id changed")
    if current.header.family != previous.header.family:
        raise VersionError("artifact family changed")
    wanted = previous.header.revision + 1
    if current.header.revision != wanted:
        raise VersionError(f"expected revision {wanted}, got {current.header.revision}")
    if current.header.time.created != previous.header.time.created:
        raise VersionError("created timestamp changed")


def is_semantic_change(previous: Artifact | None, current: Artifact) -> bool:
    """Compare payload and semantic header fields without counting strength-only changes.

    比较内容及语义头字段，不将纯强度变化计入。
    """
    if previous is None:
        return True
    if previous.payload != current.payload:
        return True
    names = ("family", "state", "scope", "subject_id", "shareable")
    return any(getattr(previous.header, n) != getattr(current.header, n) for n in names)
