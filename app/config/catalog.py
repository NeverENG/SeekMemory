"""Host-neutral inventory of existing configuration keys and exposure levels.

These labels classify existing inputs; they do not alter host UI or policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from .defaults import GROUPS

Level = Literal["basic", "advanced", "internal"]
Stability = Literal["stable", "experimental"]


@dataclass(frozen=True)
class ConfigField:
    group: str
    level: Level
    default: object
    stability: Stability


# Only choices a user might normally need to supply. Empty input remains valid.
_BASIC = frozenset({"owner_umo", "open_to", "observe_groups", "trusted"})
# Existing optional controls, not a recommendation to show every field in the UI.
_ADVANCED = frozenset({
    "db_path", "budget_chars", "recall_k", "source_recall_enabled",
    "dream_enabled", "dream_time", "summary_time", "weekly_day",
    "relationship_mode", "attention_policy_enabled", "proactive_enabled",
    "runtime_gate_enabled", "runtime_tool_filter_enabled", "debug_log",
})
_EXPERIMENTAL = frozenset({
    "runtime_gate_enabled", "runtime_tool_filter_enabled", "proactive_enabled",
})

FIELDS: Mapping[str, ConfigField] = MappingProxyType({
    key: ConfigField(
        group=group,
        level=("basic" if key in _BASIC else "advanced" if key in _ADVANCED else "internal"),
        default=value,
        stability="experimental" if key in _EXPERIMENTAL else "stable",
    )
    for group, values in GROUPS.items()
    for key, value in values.items()
})
