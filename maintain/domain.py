"""Explicit maintenance entries and prepared revision data; re-exports only.

明确维护入口及已准备版本数据，仅导出；原实现路径保持可用。
"""
from .decay import decay_all
from .lifecycle import forget_expired
from .merge import merge_similar
from .impression import revise_impression
from .self_impression import build_self_impressions, promote_self_candidates
from .persona import compose, distill_persona, distill_self_persona
from .relationship import consolidate_relationships
from .link import link_new, persist
from .reflect import signals, should_reflect
from .promote import promote_candidates
from .plans import RevisionWrite, RevisionPlan

__all__ = [
    "decay_all", "forget_expired", "merge_similar", "revise_impression", "build_self_impressions",
    "promote_self_candidates", "compose", "distill_persona", "distill_self_persona",
    "consolidate_relationships", "link_new", "persist", "signals", "should_reflect", "promote_candidates",
    "RevisionWrite", "RevisionPlan",
]
