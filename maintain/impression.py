"""Read impression rivals, prepare one atomic merge and update cache after commit.

读取印象对手，准备一个原子合并并在提交后更新缓存。
"""

from __future__ import annotations

from .writer import MaintenanceWriter

from dataclasses import replace

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, content_of, revise
    from .ports import ArtifactCache, ArtifactStore
    from ..app.text_rules import alphanumeric_bigrams as bigrams
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, content_of, revise
    from maintain.ports import ArtifactCache, ArtifactStore
    from app.text_rules import alphanumeric_bigrams as bigrams

from .impression_policy import (
    FAMILY, LEVEL, REINFORCE_OVERLAP, REVISE_CONTAIN, REVISE_DICE, MIN_GRAMS, WEIGHT_STEP, WEIGHT_CAP,
    _text, _compare, _merged_sources, rivals, best_match, reinforced, reworded,
)
from .plans import RevisionPlan, RevisionWrite


def _rivals(cache: ArtifactCache, art: Artifact) -> list[Artifact]:
    """Read matching subject/scope rivals / 读取相同主体及范围的候选旧印象。"""
    return rivals(cache.active("memory"), art)


def _best_match(cache: ArtifactCache, art: Artifact) -> tuple[Artifact | None, float, float]:
    """Read the best existing impression match / 读取最佳已有印象匹配。"""
    return best_match(cache.active("memory"), art)


def revise_impression(artifacts: ArtifactStore, cache: ArtifactCache, art: Artifact,
                      *, writer: MaintenanceWriter | None = None) -> Artifact | None:
    """Prepare and atomically merge an already stored impression, preserving version history / 准备并原子合并已保存印象，保留版本历史。"""
    writer = writer or MaintenanceWriter(artifacts, cache)
    writer.ensure_ready()
    if art.header.family != FAMILY:
        return None
    if str(art.payload.get("level") or "") != LEVEL:
        return None
    old, dice, contain = _best_match(cache, art)
    if old is None:
        return None
    weight = min(WEIGHT_CAP, max(float(old.header.strength.weight),
                                 float(art.header.strength.weight)) + WEIGHT_STEP)
    hits = int(old.header.strength.hits or 0) + 1
    if dice >= REINFORCE_OVERLAP:
        return _reinforce(artifacts, cache, art, old, weight, hits, writer=writer)
    if contain >= REVISE_CONTAIN and dice >= REVISE_DICE:
        # Preserve containment/length guards against accidental one-word merges.
        # 保留包含及长度条件，避免仅共用一词就意外合并。
        short = min(len(bigrams(_text(art))), len(bigrams(_text(old)))) < MIN_GRAMS
        if contain < 0.9 and short:
            return None
        return _reword(artifacts, cache, art, old, weight, hits, dice, writer=writer)
    return None


def _reinforce(artifacts: ArtifactStore, cache: ArtifactCache, art: Artifact, old: Artifact,
               weight: float, hits: int, *, writer: MaintenanceWriter | None = None) -> Artifact:
    """Prepare reinforcement then use the single merge writer / 准备强化后使用唯一合并写入流程。"""
    return _commit_merge(artifacts, cache, art, reinforced(art, old, weight, hits),
                         reason="impression reinforced", writer=writer)


def _reword(artifacts: ArtifactStore, cache: ArtifactCache, art: Artifact, old: Artifact,
            weight: float, hits: int, score: float, *, writer: MaintenanceWriter | None = None) -> Artifact:
    """Prepare wording then use the single merge writer / 准备措辞后使用唯一合并写入流程。"""
    return _commit_merge(artifacts, cache, art, reworded(art, old, weight, hits, score),
                         reason=f"impression revised: {score:.2f}", writer=writer)


def _commit_merge(artifacts: ArtifactStore, cache: ArtifactCache, art: Artifact,
                  new: Artifact, *, reason: str, writer: MaintenanceWriter | None = None) -> Artifact:
    """Commit revised old and retired incoming impressions atomically before cache / 在缓存前原子提交修订旧印象及停用传入印象。"""
    retired = revise(art, state="merged")
    plan = RevisionPlan((
        RevisionWrite(new, new.header.revision - 1, tuple(new.header.lineage.sources)),
        RevisionWrite(retired, art.header.revision, tuple(art.header.lineage.sources)),
    ), "merge", reason)
    (writer or MaintenanceWriter(artifacts, cache)).execute(plan)
    return new
