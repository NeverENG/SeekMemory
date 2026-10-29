"""Read bounded Source evidence to find current memories, never inject raw Source.

限量读取原始证据以查找当前记忆，绝不注入原始消息正文；不拥有连接或写入能力。
"""
from __future__ import annotations

import datetime

try:
    from ..app.ports import ArtifactStore, SourceStore
except ImportError:
    from app.ports import ArtifactStore, SourceStore
from .scope import visible
from .designated import deliverable
from .temporal import filter_valid, in_window
from .source_query import query_recent


def supplement(picked: list, *, mode: str, text: str, sources: SourceStore,
               artifacts: ArtifactStore, conf, umo: str, owner_umo: str,
               speaker: str, private: bool, lookup, window, log) -> dict:
    """Append eligible current memories to picked and return content-free counts.

    将符合条件的当前记忆加入候选，返回无正文计数；不写入记忆或缓存。
    """
    source_info = {
        "enabled": True,
        "candidates": 0,
        "artifacts": 0,
        "picked": 0,
    }
    recall_k = max(0, int(conf("recall_k", 8)))
    threshold = min(2, recall_k)
    if len(picked) < threshold and mode != "none":
        try:
            hours = max(1, int(conf("source_recall_hours", 12)))
            max_candidates = max(1, int(conf("source_recall_max_candidates", 80)))
            since = (
                datetime.datetime.now() - datetime.timedelta(hours=hours)
            ).isoformat(timespec="seconds")
            recent = sources.recent_sources(
                since=since, limit=max_candidates
            )
            hits = query_recent(
                text,
                recent,
                session_id=umo,
                speaker=speaker,
                limit=max_candidates,
            )
            source_info["candidates"] = len(hits)
            source_ids = [hit.source_id for hit in hits]
            if source_ids:
                rank_by_source = {
                    source_id: index
                    for index, source_id in enumerate(source_ids)
                }
                source_arts = sorted(
                    (
                        art
                        for art in artifacts.by_source_ids(source_ids)
                        if art.header.family != "relationship"
                    ),
                    key=lambda art: (
                        min(
                            (
                                rank_by_source[source]
                                for source in art.header.lineage.sources
                                if source in rank_by_source
                            ),
                            default=len(source_ids),
                        ),
                        art.header.id,
                        str(art.header.time.created or ""),
                    ),
                )
                source_info["artifacts"] = len(source_arts)
                existing = {art.header.id for art in picked}
                eligible = []
                for art in source_arts:
                    if art.header.id in existing:
                        continue
                    if not visible([art], umo, owner_umo, lookup):
                        continue
                    if not deliverable(art, text, private):
                        continue
                    if not filter_valid([art]):
                        continue
                    if (
                        window is not None
                        and art.header.family == "memory"
                        and not in_window(art, window)
                    ):
                        continue
                    existing.add(art.header.id)
                    eligible.append(art)
                capacity = max(0, recall_k - len(picked))
                selected = eligible[:capacity]
                picked.extend(selected)
                source_info["picked"] = len(selected)
        except Exception as exc:  # noqa: BLE001 - Optional Source evidence / 可选原始证据。
            log(f"source recall failed: {type(exc).__name__}")
            source_info["error"] = type(exc).__name__

    return source_info
