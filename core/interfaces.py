"""Core's single interface entry / core 唯一主要接口入口。

Provides: existing domain values and operations, explicitly exported below.
提供：下列领域类型与操作；原实现和原导入路径继续有效。
Requires: the three storage/cache protocols declared at the end of this file.
需要：文件末尾声明的三组存储、缓存能力。

Declarations and exports only; implementations remain in their owning modules.
本文件仅声明、导出接口，不实现业务；Graph/Tree 的导入绑定由私有模块处理。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ._interface_bindings import __dir__, __getattr__

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
# Tree: children/impressions read; add_under commits then updates cache/relations.
# 树：子节点和印象查询只读；添加节点依次提交记忆、更新缓存、写关系，非整体事务。
# Lazy exports preserve object identity without an initialization cycle / 延迟导出保留原对象，避免初始化循环。
if TYPE_CHECKING:
    from .graph import ArtifactEdge, Graph, KINDS
    from .tree import Tree, EDGE_PREFIX, LEVELS

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


# Required capabilities / 要求外部提供的能力
class GraphArtifactStore(Protocol):
    """Storage needed by Graph; caller owns its lifetime / 图所需存储，生命周期由外部管理。"""

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Upsert by (src, dst, kind); errors propagate / 按两端及类型写入或更新，错误向上传递。"""
        ...

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read (other ID, kind, weight) from both ends; direction omitted / 双向查询，返回另一端、类型、权重，不含方向。"""
        ...


class TreeArtifactStore(Protocol):
    """Storage needed by Tree; separate calls are not one transaction / 树所需存储，多次调用不是一个整体事务。"""

    def get(self, node_id: str) -> Artifact | None:
        """Read the current revision, or None if absent / 读取当前版本，不存在返回空。"""
        ...

    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple = ()) -> None:
        """Atomically save revision/evidence/ledger; expected 0 creates, conflicts raise VersionError.

        原子保存版本、证据和账本；新建预期版本为 0，版本冲突抛 VersionError；不更新缓存。
        """
        ...

    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]:
        """Read by optional family/state; None omits that filter / 按类型、状态筛选，空值表示不限制该项。"""
        ...

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read (other ID, kind, weight) from both ends; direction omitted / 双向查询连接，返回另一端、类型、权重，不含方向。"""
        ...

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Upsert one edge; does not change the parent column / 写入或更新一条连接，不修改父节点字段。"""
        ...

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """Set/clear only the parent column; absent child is a no-op / 仅设置或清空父字段，不维护连接；子节点不存在则无操作。"""
        ...


class TreeCache(Protocol):
    """Optional active-memory cache; no persistence / 可选的有效记忆缓存，不负责持久化。"""

    def get(self, node_id: str) -> Artifact | None:
        """Read cached value; None does not prove storage absence / 读取缓存；未命中不表示数据库中不存在。"""
        ...

    def put(self, art: Artifact) -> None:
        """Replace active values, remove inactive ones; call after commit / 更新有效记忆，移除非有效记忆；提交成功后调用。"""
        ...

    def by_level(self, level: str) -> list[Artifact]:
        """Read cached active values at one abstraction level / 读取指定抽象层级的有效缓存记忆。"""
        ...


__all__ = [
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
    "ArtifactEdge", "Graph", "KINDS", "Tree", "EDGE_PREFIX", "LEVELS",
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
    "GraphArtifactStore", "TreeArtifactStore", "TreeCache",
]
