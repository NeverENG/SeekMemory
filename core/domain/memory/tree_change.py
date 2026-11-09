"""Immutable, bounded tree write intent; no storage or model dependencies.

树重建写入意图；不持有存储或模型资源。
"""

from __future__ import annotations

from dataclasses import dataclass

from .artifact import Artifact


@dataclass(frozen=True)
class TreeLink:
    parent: str
    child: str
    weight: float = 1.0


@dataclass(frozen=True)
class TreeRevision:
    artifact: Artifact
    expected_revision: int
    source_ids: tuple[str, ...]


@dataclass(frozen=True)
class TreeChange:
    """Explicit operation ID, observed heads and complete inbound snapshots per child."""

    operation_id: str
    writes: tuple[TreeRevision, ...]
    observed: tuple[tuple[str, int], ...]
    edges_before: tuple[tuple[str, tuple[TreeLink, ...]], ...]
    edges_after: tuple[tuple[str, tuple[TreeLink, ...]], ...]
    op: str
    reason: str
