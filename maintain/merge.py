"""Read identity-scoped clusters, prepare per-cluster atomic revisions and publish cache.

读取身份范围内的聚类，准备各聚类原子版本后发布缓存。
"""

from __future__ import annotations

from .writer import MaintenanceWriter

import datetime
import re
from collections import Counter

try:  # Plugin namespace / 插件命名空间。
    from ..core.domain.memory.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from .ports import ArtifactCache, ArtifactStore
except ImportError:  # Top-level package / 顶层包。
    from core.domain.memory.artifact import (
        Artifact,
        Lineage,
        Strength,
        TimeSpan,
        content_of,
        make,
        revise,
    )
    from maintain.ports import ArtifactCache, ArtifactStore

MAX_ACTIVE = 500
MERGE_LEVELS = ("scene", "detail")


from .merge_policy import (
    DEFAULT_MERGE_THRESHOLD, _clean, _bigrams, _similarity, _text_of, _summarize_texts, _cluster_indices, _majority, cluster_plan,
)


def merge_similar(
    artifacts: ArtifactStore, cache: ArtifactCache, threshold: float = DEFAULT_MERGE_THRESHOLD, limit: int = 50,
    *, writer: MaintenanceWriter | None = None,
) -> int:
    """Commit each eligible same-subject/scope cluster atomically; clusters are independent / 原子提交每个符合条件的同主体及范围聚类，各聚类彼此独立。"""
    writer = writer or MaintenanceWriter(artifacts, cache)
    writer.ensure_ready()
    pool = [
        art
        for art in list(cache.by_level("scene")) + list(cache.by_level("detail"))
        if art.header.state == "active"
    ]
    if len(pool) <= MAX_ACTIVE:
        return 0

    groups: dict[tuple[str, str], list[Artifact]] = {}
    for art in pool:
        key = (str(art.header.subject_id or ""), str(art.header.scope or "private"))
        groups.setdefault(key, []).append(art)

    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    made = 0
    per_group_limit = max(int(limit), 3)
    ordered = sorted(
        groups.values(),
        key=lambda group: min(
            art.header.time.created or art.header.time.updated or "" for art in group
        ),
    )

    for group in ordered:
        group.sort(
            key=lambda art: art.header.time.created or art.header.time.updated or ""
        )
        batch = group[:per_group_limit]
        if len(batch) < 3:
            continue
        texts = [_text_of(art) for art in batch]
        clusters = _cluster_indices(texts, threshold)
        for indices in clusters:
            members = [batch[index] for index in indices]
            plan = cluster_plan(members, [texts[index] for index in indices], now)
            writer.execute(plan)
            made += 1
    return made
