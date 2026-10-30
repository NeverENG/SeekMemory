"""Prepare the existing Tree/legacy-persist CAS replacement without writes.

准备既有树及旧持久化入口的预期版本替换，不执行写入或改变父连接语义。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .ports import TreeArtifactStore
try:
    from ..core.domain.memory.artifact import Artifact, revise
except ImportError:
    from core.domain.memory.artifact import Artifact, revise


@dataclass(frozen=True)
class PreparedRevision:
    """One replacement, expected head and operation / 一个替换版本、预期当前版本及操作。"""
    artifact: Artifact
    expected_revision: int
    op: str


def prepare_revision(art: Artifact, artifacts: TreeArtifactStore) -> PreparedRevision:
    """Read current head and preserve existing replacement semantics without writing.

    读取当前版本并保留既有替换语义，不执行写入。
    """
    existing = artifacts.get(art.header.id)
    if existing is None:
        expected = 0
        op = "create"
    else:
        expected = existing.header.revision
        op = "revise"
        if art.header.revision <= existing.header.revision:
            art = revise(
                existing,
                payload=art.payload,
                state=art.header.state,
                scope=art.header.scope,
                strength=art.header.strength,
                lineage=art.header.lineage,
                said_by=art.header.said_by,
                shareable=art.header.shareable,
                subject_id=art.header.subject_id,
            )
    return PreparedRevision(art, expected, op)
