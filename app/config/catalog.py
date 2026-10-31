"""Host-neutral inventory of existing configuration keys and policy groups.

The manifest describes compatibility input. It neither enables policies nor
changes the host UI; input validation is advisory in this issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping

from .defaults import GROUPS

Level = Literal["basic", "advanced", "internal"]
Stability = Literal["stable", "experimental", "deprecated"]


@dataclass(frozen=True)
class ConfigField:
    group: str
    level: Level
    default: object
    stability: Stability
    kind: type
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[str, ...] = ()
    restart_required: bool = False
    alias: str | None = None


@dataclass(frozen=True)
class PolicyGroup:
    id: str
    label: str
    description: str
    mode_key: str | None = None

    @property
    def advanced_overrides(self) -> tuple[str, ...]:
        """Advanced optional inputs already present in this policy group."""
        return tuple(key for key, field in FIELDS.items()
                     if field.group == self.id and field.level == "advanced")


POLICIES: Mapping[str, PolicyGroup] = MappingProxyType({
    "project": PolicyGroup("project", "Project / 项目", "Access, ownership, persistence and diagnostics / 访问、归属、持久化及诊断", "open_to"),
    "ingest": PolicyGroup("ingest", "Ingest / 抽取", "Buffer and extraction cadence / 缓冲与抽取频率"),
    "recall": PolicyGroup("recall", "Recall / 召回", "Read-only retrieval and context budget / 只读检索与上下文预算"),
    "maintenance": PolicyGroup("maintenance", "Maintenance / 维护", "Checkpoint and persona synthesis / 检查点与人格综合"),
    "dream": PolicyGroup("dream", "Dream / 夜间整理", "Nightly schedule and model budget / 夜间调度与模型预算"),
    "observability": PolicyGroup("observability", "Observability / 可观测性", "Diagnostics retention without message content / 无正文诊断保留"),
    "relationship": PolicyGroup("relationship", "Relationship / 关系", "Relationship observation and optional enforcement / 关系观察与可选执行", "relationship_mode"),
    "attention": PolicyGroup("attention", "Attention / 注意力", "Reply eligibility and follow-up / 回复资格与跟进"),
    "proactive": PolicyGroup("proactive", "Proactive / 主动调度", "Idle conversation scheduling / 空闲会话调度"),
    "runtime": PolicyGroup("runtime", "Runtime / 运行时", "Deferred dispatch and retries / 延迟执行与重试"),
})

# Only choices a user might normally need to supply. Empty input remains valid.
_BASIC = frozenset({"owner_umo", "open_to", "observe_groups", "trusted"})
_ADVANCED = frozenset({
    "db_path", "budget_chars", "recall_k", "source_recall_enabled",
    "dream_enabled", "dream_time", "summary_time", "weekly_day",
    "relationship_mode", "attention_policy_enabled", "proactive_enabled",
    "runtime_gate_enabled", "runtime_tool_filter_enabled", "debug_log",
})
_EXPERIMENTAL = frozenset({
    "runtime_gate_enabled", "runtime_tool_filter_enabled", "proactive_enabled",
})
# These describe valid policy input; they do not change legacy runtime coercion.
_CHOICES: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "open_to": ("owner_only", "owner_and_trusted", "everyone"),
    "relationship_mode": ("off", "observe", "enforce"),
})
_RANGES: Mapping[str, tuple[int | float, int | float | None]] = MappingProxyType({
    "weekly_day": (0, 6),
    "explore_rate": (0, 1),
    "recall_min_ev_rel": (0, 1),
    "relationship_low_private_reply_probability": (0, 1),
    "relationship_dislike_private_reply_probability": (0, 1),
})
# Some consumers snapshot these values at composition; other reads remain live.
_RESTART = frozenset({
    "db_path", "owner_umo", "open_to", "observe_groups", "trusted",
    "budget_chars", "context_system_chars", "group_context_messages",
    "history_messages", "source_recall_enabled", "source_recall_hours",
    "source_recall_max_candidates", "relationship_mode",
    "relationship_low_private_reply_probability",
    "relationship_dislike_private_reply_probability",
    "runtime_gate_enabled", "runtime_wait_seconds", "attention_followup_rounds",
    "attention_owner_always_reply", "proactive_enabled", "trace_retention_days",
    "trace_max_rows",
})

FIELDS: Mapping[str, ConfigField] = MappingProxyType({
    key: ConfigField(
        group=group,
        level=("basic" if key in _BASIC else "advanced" if key in _ADVANCED else "internal"),
        default=value,
        stability="experimental" if key in _EXPERIMENTAL else "stable",
        kind=type(value),
        minimum=_RANGES[key][0] if key in _RANGES else (0 if type(value) in (int, float) else None),
        maximum=_RANGES[key][1] if key in _RANGES else None,
        choices=_CHOICES.get(key, ()),
        restart_required=key in _RESTART,
    )
    for group, values in GROUPS.items()
    for key, value in values.items()
})
