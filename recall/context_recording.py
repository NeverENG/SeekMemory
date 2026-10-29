"""Explicit context-injection write use case, separate from recall queries.

明确的上下文注入记录用例，与召回查询分开；存储及缓存由调用方管理。
"""
from __future__ import annotations

try:
    from ..app.ports import ArtifactStore, ArtifactCache
except ImportError:
    from app.ports import ArtifactStore, ArtifactCache
from .designated import mark_given


def record_context(artifacts: ArtifactStore, cache: ArtifactCache,
                   block: str, info: dict) -> int:
    """Mark included designated bodies given; model/send success is irrelevant.

    将已包含在上下文中的指定正文标为已给出，与模型或发送成功无关；预览不调用本入口。
    """
    if not block or artifacts is None:
        return 0
    final_ids = set(info.get("final_ids", ()))
    arts = []
    for entity in dict.fromkeys(info.get("designated_ids", ())):
        if entity not in final_ids:
            continue
        try:
            art = artifacts.get(entity)
        except Exception:
            continue
        if art is not None:
            arts.append(art)
    return mark_given(artifacts, cache, arts, block)
