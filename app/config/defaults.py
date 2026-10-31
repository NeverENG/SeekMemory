"""SeekMemory-owned defaults; host schemas are projections, not policy owners."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

# Grouping describes ownership, not a set of user-facing settings.
_GROUPS: dict[str, dict[str, object]] = {
    'project': {
        'owner_umo': '',
        'open_to': 'owner_only',
        'observe_groups': True,
        'trusted': '',
        'db_path': '',
        'debug_log': False,
    },
    'ingest': {
        'max_sessions_per_flush': 6,
        'idle_flush_seconds': 0,
        'min_pending': 8,
        'max_flushes_per_day': 2,
        'backlog_flush_at': 30,
        'topic_ttl_seconds': 86400,
        'ingest_enabled': True,
        'ingest_interval_seconds': 600,
        'ingest_min_pending': 20,
        'ingest_batch_topics': 20,
    },
    'recall': {
        'budget_chars': 600,
        'source_recall_enabled': True,
        'source_recall_hours': 12,
        'source_recall_max_candidates': 80,
        'recall_k': 8,
        'explore_rate': 0.1,
        'recall_min_ev_abs': 0.5,
        'recall_min_ev_rel': 0.3,
        'bm25_enabled': True,
        'bm25_weight': 1.0,
        'context_system_chars': 1600,
        'group_context_messages': 20,
        'history_messages': 24,
    },
    'maintenance': {
        'enable_reflect': True,
        'max_episodes': 500,
        'checkpoint_seconds': 1800,
        'capacity_thresholds': '',
        'persona_synthesis_enabled': True,
        'persona_synthesis_interval_days': 7,
        'persona_synthesis_evidence_limit': 8,
        'persona_synthesis_evidence_chars': 2400,
    },
    'dream': {
        'summary_time': '23:50',
        'weekly_day': 6,
        'dream_enabled': True,
        'dream_time': '03:30',
        'dream_max_batches': 12,
        'dream_max_calls': 12,
        'dream_batch_tokens': 6000,
        'dream_token_budget': 60000,
    },
    'observability': {
        'trace_retention_days': 7,
        'trace_max_rows': 5000,
        'runtime_episode_retention_days': 30,
        'runtime_episode_max_rows': 5000,
    },
    'relationship': {
        'relationship_mode': 'observe',
        'relationship_private_weight': 1.0,
        'relationship_group_weight': 0.5,
        'relationship_low_private_reply_probability': 0.8,
        'relationship_dislike_private_reply_probability': 0.5,
    },
    'attention': {
        'attention_address_names': '大肥鱼,肥鱼',
        'attention_policy_enabled': True,
        'attention_followup_rounds': 3,
        'attention_owner_always_reply': True,
    },
    'proactive': {
        'proactive_enabled': False,
        'proactive_idle_seconds': 1800,
    },
    'runtime': {
        'runtime_gate_enabled': False,
        'runtime_wait_seconds': 5,
        'runtime_tick_seconds': 5,
        'runtime_dispatch_max_attempts': 3,
        'runtime_dispatch_backoff_seconds': 2,
        'runtime_tool_filter_enabled': False,
    },
}

GROUPS: Mapping[str, Mapping[str, object]] = MappingProxyType(
    {name: MappingProxyType(values) for name, values in _GROUPS.items()}
)
DEFAULTS: Mapping[str, object] = MappingProxyType(
    {key: value for values in _GROUPS.values() for key, value in values.items()}
)
