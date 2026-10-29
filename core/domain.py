"""Provided domain interface / 对外提供的领域能力入口。

Provides: domain values and operations, explicitly exported below.
提供：下列领域类型与操作；实现保留在各自模块中。
Required external capabilities are declared separately in ports.py.
外部需要提供的能力单独声明于 ports.py。

Declarations and exports only; implementations remain in their owning modules.
本文件仅导出领域接口，不实现业务。
"""

from __future__ import annotations

# Provided capabilities / 对外提供的能力
# Values keep their original definitions and defaults / 类型及默认值沿用原定义。
from .artifact import (
    FAMILIES, Artifact, Header, Lineage, Strength, TimeSpan,
    make,        # Construct without payload validation or persistence / 构造，不校验或落库。
    revise,      # Copy into a revision; no database write / 生成修订对象，不写数据库。
    validate,    # Validate family payload; raise ValueError / 校验内容，失败抛 ValueError。
    content_of,  # Read content; does not authorize disclosure / 读取文本，不代表允许披露。
)
from .source import (
    ROLES, Source,
    content_hash,    # Hash message text / 计算正文指纹。
    make_source_id,  # Stable identity from event/message fields / 按事件或消息字段生成稳定编号。
)
from .versioning import (
    OPS, CHECKPOINT_OPS, StateEvent, VersionError,
    assert_next_revision,  # Check identity, revision and creation time / 校验编号、版本与创建时间。
    is_semantic_change,    # Compare payload and semantic header fields / 比较内容与语义头字段。
)
from .retrieval import RetrievalCandidate  # Candidate value, not a retriever / 候选数据，不执行检索。

from .strength import (
    BASE_DAYS, HIT_STEP, COOLDOWN, SHAPE_FACTORS, REINFORCE_DELTAS,
    retention,        # Return retention in [0, 1] / 返回留存率。
    decayed_weight,   # Return weight after decay / 返回衰减后的权重。
    reinforce,        # Return a new Strength; no persistence / 返回新强度，不负责保存。
    hit_cooldown_ok,  # Decide whether a hit is outside cooldown / 判断命中是否已过冷却期。
)
from .disclosure import (
    FULL_MIN, PARAPHRASE_MIN, HINT_MIN,
    DisclosureLevel, RecallScene, DisclosureDecision,
    scope_prior,       # Scope contribution to disclosure score / 可见范围对披露分数的影响。
    sensitivity_of,    # Secret/shadow sensitivity / 秘密、影子内容的敏感程度。
    context_affinity,  # Context/subject affinity; not a visibility gate / 场景关联度，不是权限门。
    audience_overlap,  # Compatibility alias for context_affinity / 保留旧版关联度接口。
    subject_fit,       # Subject and sharing contribution / 主体和分享属性的影响。
    exposure,          # Combine disclosure factors / 合成披露分数。
    decide,            # Return full/paraphrase/hint/silence / 返回披露级别。
    safe_text,         # Only full may expose original content / 仅全文级别可返回原文。
)

# Graph: link/link_causal write; degree/neighbours read / 图：连接写入，度数和邻居只读。
from .graph import ArtifactEdge, Graph, KINDS

from .capacity import (
    NORMAL, PRESSURED, SATURATED, PROTECTIVE, ENV_PREFIX,
    CapacityThresholds, CapacitySnapshot, CapacityDecision,
    CapacityGovernor,  # evaluate returns actions; does not execute them / 评估并返回动作，不执行。
    load_thresholds,  # Defaults -> environment -> map; invalid values fall back / 默认、环境、映射依次覆盖。
)
from .persona import (
    PERSONA_ORIGIN_SEED, PERSONA_ORIGIN_DREAM, PERSONA_SYNTHESIS_VERSION,
    PERSONA_ORIGINS, MIN_CORPUS_EXAMPLES, MIN_CORPUS_CHARS,
    normalize_persona_file,     # Validate/normalize an in-memory document / 校验、整理内存中的人格文档。
    persona_payload_from_file, # Build seed payload; no file I/O or write / 构造初始人格内容，不读文件或落库。
    compose_seed_evolution,    # Combine base and behavior text / 组合基础人格和行为描述。
    seed_evolution_matches,    # Check the deterministic combination / 检查组合结果是否符合约定。
)
# Existing pack validation from upstream / 上游已有的人格包校验能力。
from .persona_artwork import MAX_ARTWORK_BYTES, PNG_SIGNATURE, validate_artwork
from .persona_pack import PACK_FORMAT, MAX_PACK_BYTES, MAX_SEED_BYTES, normalize_pack
from .bot_behavior import (
    SELF_SUBJECT, MIN_EVIDENCE, MIN_CONFIDENCE, BEHAVIOR_TEXT, BEHAVIORS,
    confident,                # Check bounded confidence / 检查置信度是否达到要求。
    compose_behaviors,        # Compose only known fixed behavior text / 只组合固定行为词表。
    trusted_self_impression,  # Check impression evidence and provenance / 检查自我印象的证据和来源。
    trusted_self_persona,     # Check seed/Dream/legacy persona provenance / 检查各类人格的可信条件。
)
from .relationship import (
    RELATIONSHIP_POLICY_VERSION, HARD_GATE_CONFIDENCE,
    RelationshipBand, RelationshipSnapshot,
    relationship_id,       # Stable per-person identity / 生成人物关系的稳定编号。
    summary_for,           # Fixed band description / 返回关系档位的固定描述。
    band_for,              # Classify with hysteresis / 按带迟滞的规则划分关系档位。
    snapshot_from_payload, # Validate and read a snapshot / 校验并读取关系快照。
)
from .relationship_rules import (
    RelationshipSignal, RelationshipReason, RelationshipStrength,
    ConversationScope, EvidenceRule, EVIDENCE_RULES, RelationshipObservation,
    RelationshipScoringPolicy, ScoredRelationshipEvidence, RelationshipRevisionPlan,
    score_observation,          # Score one categorical observation / 为一条分类观察计算分数。
    plan_relationship_revision, # Return a bounded plan or None; no write / 返回有限修订计划或空，不保存。
)
from .interaction_policy import (
    INTERACTION_POLICY_VERSION, LOW_REPLY_CHARS, DISLIKE_REPLY_CHARS,
    CLOSE_PROACTIVE_KINDS, ReplyStyle, AffectionScope, InteractionRule,
    InteractionContext, InteractionGate, InteractionPolicySettings,
    stable_sample,      # Repeatable Source-based sampling / 按原始消息编号稳定采样。
    decide_interaction, # Return permissions; does not send a reply / 返回互动权限，不发送消息。
)
from .trace import (
    EVENTS, FILTERS, STATUSES, ID_LIMIT,
    ids,          # Keep bounded, valid generated identifiers / 筛选合法编号并限制数量。
    count,        # Normalize a bounded non-negative count / 整理为有界非负计数。
    choice,       # Keep an allowed string or the default / 保留合法枚举文本，否则取默认值。
    recall_data,  # Whitelist content-free recall metadata / 筛选不含正文的召回信息。
    clean_event,  # Validate/sanitize; invalid identity/time raises / 清理事件，非法编号或时间报错。
    project_runs, # Group already-clean events into runs / 将已清理事件整理成运行记录。
)


__all__ = [
    "MAX_ARTWORK_BYTES", "PNG_SIGNATURE", "validate_artwork",
    "PACK_FORMAT", "MAX_PACK_BYTES", "MAX_SEED_BYTES", "normalize_pack",
    "FAMILIES", "Artifact", "Header", "Lineage", "Strength", "TimeSpan",
    "make", "revise", "validate", "content_of",
    "ROLES", "Source", "content_hash", "make_source_id",
    "OPS", "CHECKPOINT_OPS", "StateEvent", "VersionError",
    "assert_next_revision", "is_semantic_change", "RetrievalCandidate",
    "BASE_DAYS", "HIT_STEP", "COOLDOWN", "SHAPE_FACTORS", "REINFORCE_DELTAS",
    "retention", "decayed_weight", "reinforce", "hit_cooldown_ok",
    "FULL_MIN", "PARAPHRASE_MIN", "HINT_MIN", "DisclosureLevel", "RecallScene",
    "DisclosureDecision", "scope_prior", "sensitivity_of", "context_affinity",
    "audience_overlap", "subject_fit", "exposure", "decide", "safe_text",
    "ArtifactEdge", "Graph", "KINDS",
    "NORMAL", "PRESSURED", "SATURATED", "PROTECTIVE", "ENV_PREFIX",
    "CapacityThresholds", "CapacitySnapshot", "CapacityDecision",
    "CapacityGovernor", "load_thresholds",
    "PERSONA_ORIGIN_SEED", "PERSONA_ORIGIN_DREAM", "PERSONA_SYNTHESIS_VERSION",
    "PERSONA_ORIGINS", "MIN_CORPUS_EXAMPLES", "MIN_CORPUS_CHARS",
    "normalize_persona_file", "persona_payload_from_file", "compose_seed_evolution",
    "seed_evolution_matches", "SELF_SUBJECT", "MIN_EVIDENCE", "MIN_CONFIDENCE",
    "BEHAVIOR_TEXT", "BEHAVIORS", "confident", "compose_behaviors",
    "trusted_self_impression", "trusted_self_persona",
    "RELATIONSHIP_POLICY_VERSION", "HARD_GATE_CONFIDENCE", "RelationshipBand",
    "RelationshipSnapshot", "relationship_id", "summary_for", "band_for",
    "snapshot_from_payload", "RelationshipSignal", "RelationshipReason",
    "RelationshipStrength", "ConversationScope", "EvidenceRule", "EVIDENCE_RULES",
    "RelationshipObservation", "RelationshipScoringPolicy",
    "ScoredRelationshipEvidence", "RelationshipRevisionPlan",
    "score_observation", "plan_relationship_revision",
    "INTERACTION_POLICY_VERSION", "LOW_REPLY_CHARS", "DISLIKE_REPLY_CHARS",
    "CLOSE_PROACTIVE_KINDS", "ReplyStyle", "AffectionScope", "InteractionRule",
    "InteractionContext", "InteractionGate", "InteractionPolicySettings",
    "stable_sample", "decide_interaction", "EVENTS", "FILTERS", "STATUSES",
    "ID_LIMIT", "ids", "count", "choice", "recall_data", "clean_event", "project_runs",
]
