"""Keep the legacy promotion entry using verified bot self-evidence only.

保留仅使用已验证机器人自身证据的旧晋升入口，不执行写入。
"""
from __future__ import annotations

try:
    from .ports import ArtifactCache
    from ..core.domain.memory.artifact import Artifact
except ImportError:
    from maintain.ports import ArtifactCache
    from core.domain.memory.artifact import Artifact
from .self_impression import promote_self_candidates


def promote_candidates(cache: ArtifactCache, sources, min_hits: int = 3,
                       today: str | None = None,
                       only_umo: str = "") -> list[Artifact]:
    """Filter verified self-candidates with the existing legacy hit threshold / 按既有旧命中阈值筛选已验证自身候选。"""
    return [a for a in promote_self_candidates(cache, sources, today)
            if a.header.strength.hits >= max(3, min_hits)]
