"""Apply private-trigger guards and explicitly record designated context inclusion.

应用私聊及触发词条件，并明确记录指定记忆进入上下文，资源由调用方管理。
"""

from __future__ import annotations

from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactStore
    from ..core.artifact import Artifact
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactStore
    from core.artifact import Artifact

# Legacy imports retain the original policy objects / 旧导入保留原规则对象。
from .designated_policy import triggers_of, _compact, matches, already_given, is_private, deliverable, _SPLIT


def mark_given(artifacts: ArtifactStore, cache: Any, arts: list[Artifact], block: str,
               now: str | None = None) -> int:
    """Explicitly commit given markers only for included designated bodies; isolate per-item failure / 仅为已包含的指定正文明确提交给出标记，逐条隔离失败。"""
    from .context_recording import ContextRecorder
    return ContextRecorder(artifacts, cache).record_artifacts(arts, block, now)


def current_heads(arts: list[Artifact], artifacts: ArtifactStore) -> list[Artifact]:
    """Read fresh designated heads without updating cache; failed reads withhold them.

    读取指定记忆最新版本，不更新缓存；读取失败时不提供该项，避免缓存失败后重复给出。
    """
    out = []
    for art in arts:
        if art.header.family == "designated":
            try:
                art = artifacts.get(art.header.id)
            except Exception:
                continue
            if art is None or art.header.state != "active":
                continue
        out.append(art)
    return out
