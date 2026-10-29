"""Provided application interface / 应用层对外提供的能力。

Explicit exports only; implementations remain in their owning modules.
仅集中导出与说明，不实现业务；外部依赖见 ports.py。
Existing implementation paths remain available / 原有实现路径继续可用。
"""

from __future__ import annotations

# Shared values / 跨模块交换的数据，不执行读写。
from .contracts import (
    ChatRequest,       # Provider-neutral model input / 与模型供应商无关的请求。
    ChatResponse,      # Model text and usage metadata / 模型回复及用量。
    DialogueTurn,      # Buffered Source projection / 原始消息的缓冲视图。
    ExtractionState,   # Queue state without message text / 不含正文的抽取队列状态。
    ExtractionFailure, # Completed counts on failed extraction / 失败抽取的已完成数量。
    RecallRequest,     # Narrow recall input; see usage limits in docs / 窄召回请求，接入情况见文档。
    RecallResult,      # Narrow recall output / 窄召回结果。
    WriteOutcome,      # Write counts, failures and usage / 写入数量、失败及用量。
)

# Request budgets / 请求预算；token values are estimates / token 数量为估算。
from .budget import (
    ContextBudget,       # Request limits and their display view / 请求限额及展示视图。
    budget_from_config,  # Read and normalize supplied config / 读取并规整外部提供的配置。
    clamp_chars,         # Truncate text, also returning original length / 裁剪文本并返回原长度。
    estimate_messages,   # Estimate a list of messages / 估算一组消息的用量。
    estimate_tokens,     # Estimate from character/message counts / 按字数和消息数估算用量。
)

# Extraction selection / 抽取批次选择；no persistence or model calls / 不保存或调用模型。
from .flush_policy import (
    ExtractionBatch,           # Same-session extraction input / 单会话抽取批次。
    FlushDecision,             # Whether to extract, with reason / 是否抽取及原因。
    chunk_turns,               # Split a topic, keeping reply pairs where possible / 话题分块，尽量保留问答配对。
    decide_flush,              # Apply Dream/idle/backlog gates / 判断夜间、空闲和积压条件。
    pack_same_session_batches, # Pack indivisible units within a session / 在同一会话内打包完整分块。
    select_topic_batches,      # Select topics round-robin across sessions / 按会话轮转选择话题。
)

# Write coordinators / 写入协调；these capabilities have side effects / 下列能力有副作用。
from .cache_repair import CacheRepairs
from .text_rules import alphanumeric_bigrams, word_bigrams, word_jaccard
from .value_codec import json_object
from .revision_plan import PreparedRevision, prepare_revision
from .checkpoint import CheckpointManager  # Coalesce hits, commit, then update cache / 合并命中、提交后更新缓存。
from .dream import (
    DreamCycle,   # Coordinate daily extraction, maintenance and journal / 编排每日抽取、维护及台账。
    DreamResult,  # Cycle outcome and budget summary / 整理结果及预算汇总。
)
from .persona_synthesis import (
    PersonaEvidence,        # Evidence summary supplied by the caller / 调用方提供的证据概述。
    build_persona_request,  # Build a request; does not invoke the model / 构造请求，不调用模型。
    parse_persona_draft,    # Validate a draft; None means unchanged, invalid raises / 校验草稿，无变化返回空，非法则报错。
)

# Runtime input, decisions and outcomes / 运行时输入、决策及结果。
from .runtime.contracts import (
    ActionKind, ActionRecord, ActionRequest, ActionResult, ActionStatus,
    AttentionDecision, AttentionLevel,
    MemoryContext, MemoryContextRequest,
    ProactiveDecision,
    RunContext, RunDecision, RunResult, RuntimeInput,
    SessionState, UserRunReceipt, WakeAction,
)
from .runtime.recorder import RecordedReply, RecordedTurn, RunRecorder  # Source/queue/episode write-back / 消息、队列及运行记录写回。

# Runtime policies and lifecycle / 运行时策略与生命周期；details / 细节见 runtime.md。
from .runtime.attention import DefaultAttentionPolicy  # Reply/observe decision only / 仅判断回复或观察。
from .runtime.proactive import (
    DefaultProactivePolicy,   # Evaluate quiet/cooldown/retry gates / 判断安静期、冷却和重试条件。
    ProactiveCandidate,       # One eligible session / 一个符合条件的会话。
    ProactiveDispatchPlan,    # Selected and deferred sessions / 本次选中及留待后续的会话。
    plan_proactive_dispatch,  # Order and limit eligible sessions / 对符合条件的会话排序并限量。
)
from .runtime.scheduler import DueRun, Scheduler, TimingPolicy  # Select due work, without sending / 选择到期任务，不发送。
from .runtime.runtime import AgentRuntime  # Coordinate state, generation, sending and write-back / 协调状态、生成、发送及写回。
from .runtime.worker import RuntimeWorker  # Poll, limit concurrency and deduplicate sessions / 轮询、限制并发并去重会话。
from .runtime.topics import TopicCandidate  # Read-only proactive topic / 只读的主动话题候选。

# Action execution and audit / 动作执行与审计；audit excludes message text / 审计不含消息正文。
from .runtime.actions import (
    ActionExecutor,          # Attempt -> execute -> terminal audit / 尝试记录、执行、终态记录。
    ActionLedger,            # Construct and append action audit / 构造并追加动作审计。
    ActionMessageSender,     # Compatibility send view over ActionPort / 动作接口的兼容发送视图。
    RepoActionSink,          # Map audit to the injected repository / 向注入的仓储转交审计。
    action_idempotency_key,  # Derive stable action identity / 生成稳定的动作编号。
)
from .runtime.episode import (
    EpisodeOutcome, EpisodeRecord,
    EpisodeRecorder,           # Forward one episode to its sink / 将一条运行记录交给外部存储。
    JsonlEpisodeStore,          # Existing file-backed implementation / 现有文件存储实现。
    RepoEpisodeStore,           # Existing repository-backed implementation / 现有仓储转接实现。
    delivery_failure_metadata, # Delivery failure as a field map / 将交付失败转为字段映射。
    delivery_failure_outcome,  # Delivery failure as a value / 将交付失败转为结果对象。
    episode_outcome,           # Classify delivery/tool failures / 归类交付及工具失败。
    normalize_tool_calls,      # Retain tool names, omit arguments/results / 仅保留工具名，去掉参数和结果。
    safe_error_code,           # Keep a bounded code, omit exception text / 仅保留有界错误码，去掉异常正文。
)

# Existing persistence adapters / 现有状态存储实现；included to inventory the current surface / 纳入当前接口盘点。
from .runtime.state import InMemoryStateStore, JsonStateStore, RepoStateStore
from .runtime.tools import (
    ToolCall, ToolGuardDecision,
    ToolPolicy,          # Filter before model requests; observation does not enforce / 请求前过滤，观察回调不执行拦截。
    tool_result_failed,  # Inspect failure metadata only / 仅识别失败元信息。
    trace_tool_call,     # Compatibility wrapper for observed calls / 记录工具调用的兼容函数。
)
from .runtime.tracing import RunTracer  # Host event correlation and diagnostic writes / 宿主事件关联及诊断写入。

__all__ = [
    "ChatRequest", "ChatResponse", "DialogueTurn", "ExtractionState", "ExtractionFailure",
    "RecallRequest", "RecallResult", "WriteOutcome",
    "ContextBudget", "budget_from_config", "clamp_chars", "estimate_messages", "estimate_tokens",
    "ExtractionBatch", "FlushDecision", "chunk_turns", "decide_flush",
    "pack_same_session_batches", "select_topic_batches",
    "alphanumeric_bigrams", "word_bigrams", "word_jaccard", "json_object",
    "PreparedRevision", "prepare_revision", "CacheRepairs", "CheckpointManager", "DreamCycle", "DreamResult",
    "PersonaEvidence", "build_persona_request", "parse_persona_draft",
    "ActionKind", "ActionRecord", "ActionRequest", "ActionResult", "ActionStatus",
    "AttentionDecision", "AttentionLevel", "MemoryContext", "MemoryContextRequest",
    "ProactiveDecision", "RunContext", "RunDecision", "RunResult", "RuntimeInput",
    "SessionState", "UserRunReceipt", "WakeAction", "RecordedReply", "RecordedTurn", "RunRecorder",
    "DefaultAttentionPolicy", "DefaultProactivePolicy", "ProactiveCandidate", "ProactiveDispatchPlan",
    "plan_proactive_dispatch", "DueRun", "Scheduler", "TimingPolicy", "AgentRuntime", "RuntimeWorker",
    "TopicCandidate", "ActionExecutor", "ActionLedger", "ActionMessageSender", "RepoActionSink",
    "action_idempotency_key", "EpisodeOutcome", "EpisodeRecord", "EpisodeRecorder",
    "JsonlEpisodeStore", "RepoEpisodeStore", "delivery_failure_metadata", "delivery_failure_outcome",
    "episode_outcome", "normalize_tool_calls", "safe_error_code",
    "InMemoryStateStore", "JsonStateStore", "RepoStateStore",
    "ToolCall", "ToolGuardDecision", "ToolPolicy", "tool_result_failed", "trace_tool_call", "RunTracer",
]
