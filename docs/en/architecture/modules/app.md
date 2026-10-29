# app: Ports, DTOs, and Application Policies

## Responsibility

app provides shared application values, external capability declarations, and policies. It currently also contains daily-cycle coordination, reinforcement write-back, runtime execution, and some persistence adapters; the directory as a whole is not a pure policy layer.

## Two interface entry points

- [app/domain.py](../../../../app/domain.py): what the application provides. It explicitly exports 79 types, functions, and execution classes, with descriptions only; implementations remain in their owning files.
- [app/ports.py](../../../../app/ports.py): what callers must supply. It explicitly lists 33 protocols and five callback type aliases, with declarations or exports only and no I/O implementation.

This step centralizes interface entry points, covering top-level app capabilities, the existing runtime `__all__`, and other actual cross-module calls. Existing import paths remain available and callers have not all migrated; original runtime value/protocol definitions also remain in place. Constants stay with their owning policies rather than all becoming application interfaces.

### domain: shared values

| Interface | Purpose | Definition |
| --- | --- | --- |
| `DialogueTurn`, `ExtractionState` | Buffered message projection and extraction queue state | `app/contracts.py` |
| `ChatRequest`, `ChatResponse`, `WriteOutcome` | Model input/output and write/usage summary | `app/contracts.py` |
| `RecallRequest`, `RecallResult` | Narrow recall input/output; production `RecallService.build` still uses parameters and a tuple instead | `app/contracts.py` |
| `ContextBudget` | Request limits with estimation and display helpers | `app/budget.py` |
| `FlushDecision`, `ExtractionBatch` | Extraction decision/reason and same-session batch | `app/flush_policy.py` |
| `DreamResult`, `PersonaEvidence` | Daily-cycle result and persona revision evidence summary | `app/dream.py`, `app/persona_synthesis.py` |
| `RuntimeInput`, `RunContext`, `UserRunReceipt`, `RunResult` | Inbound event, pending run, acceptance receipt, delivery result | `app/runtime/contracts/events.py` |
| `AttentionLevel`, `WakeAction`, `AttentionDecision`, `RunDecision` | Attention, reply action, and policy decisions | `app/runtime/contracts/events.py` |
| `SessionState`, `ProactiveDecision` | Mutable session scheduling state and proactive eligibility | `app/runtime/contracts/sessions.py`, `proactive.py` |
| `MemoryContextRequest`, `MemoryContext` | Read-only memory context input/output | `app/runtime/contracts/ports.py` |
| `ActionKind`, `ActionStatus`, `ActionRequest`, `ActionResult`, `ActionRecord` | Action vocabulary, execution input/output, content-free audit | `app/runtime/contracts/actions.py` |
| `RecordedTurn`, `RecordedReply` | Identity/counts after Source write-back | `app/runtime/recorder.py` |
| `ProactiveCandidate`, `ProactiveDispatchPlan`, `DueRun`, `TopicCandidate` | Proactive selection, due work, topic candidate | `app/runtime/proactive.py`, `scheduler.py`, `topics.py` |
| `EpisodeRecord`, `EpisodeOutcome`, `ToolCall`, `ToolGuardDecision` | Episode outcome, tool observation and filter decision | `app/runtime/episode.py`, `tools.py` |

### domain: policies and executable capabilities

Complexity below means the difficulty of understanding prerequisites, state, and failure paths, not line count or execution cost.

| Interface | Responsibility and effects | Logical complexity / coupling |
| --- | --- | --- |
| `budget_from_config` | Read supplied configuration and normalize a budget | Low / low |
| `estimate_tokens`, `estimate_messages` | Estimate usage from character/message counts, not exact tokenization | Low / low |
| `clamp_chars` | Truncate text and return its original length | Low / low |
| `decide_flush` | Apply Dream, expiry, daily cap, backlog, and idle conditions | Medium / low |
| `select_topic_batches` | Select topics round-robin across sessions | Medium / low |
| `chunk_turns` | Split oversized topics, preserving reply pairs where possible | Medium / low |
| `pack_same_session_batches` | Pack same-session units within a budget without splitting indivisible units | Medium / low |
| `build_persona_request` | Construct a persona revision request without calling a model | Medium / low |
| `parse_persona_draft` | Validate a draft; unchanged text returns None, invalid content raises | Medium / low |
| `CheckpointManager` | `record/due/pending/flush`: coalesce hits, commit revisions, then update cache | Medium / high |
| `DreamCycle` | `enabled/due/run/status`: daily eligibility, extraction loop, maintenance, journal | High / high |
| `DefaultAttentionPolicy` | `evaluate`: reply/observe decision and follow-up adjustment | Low / low |
| `DefaultProactivePolicy`, `plan_proactive_dispatch` | Evaluate eligibility, order and limit due sessions without state I/O | Medium / low |
| `TimingPolicy`, `Scheduler` | `evaluate/due/proactive_due`: timing decisions and read-only task selection, no sending | Low / medium |
| `AgentRuntime` | Inbound acceptance, context, delivery callbacks, deferred/proactive execution, state transitions | High / high |
| `RuntimeWorker` | `dispatch/dispatch_proactive/tick/run_forever`: polling, concurrency limits, in-process session deduplication | High / high |
| `RunRecorder` | Run identity, user/assistant Sources, pending views, hits, delivery audit | High / high |
| `action_idempotency_key` | Derive stable identity from session, run, action, and callback | Low / low |
| `ActionLedger`, `ActionExecutor` | `begin/finish/execute`: attempt records, host execution, terminal audit | Medium / medium |
| `ActionMessageSender` | `send`: adapt legacy text delivery to the action port | Low / medium |
| `EpisodeRecorder` | `record`: forward one episode to its sink | Low / low |
| `safe_error_code`, `normalize_tool_calls` | Keep bounded error codes/tool names, omit exception text, arguments, results | Low / low |
| `episode_outcome`, `delivery_failure_outcome`, `delivery_failure_metadata` | Classify delivery/tool failures into values or field maps | Low / low |
| `ToolPolicy`, `tool_result_failed`, `trace_tool_call` | Tool decisions, filtering, observations and failure metadata; filtering manipulates host-shaped objects | Medium / high |
| `RunTracer` | Correlate host events and write request, response, tool, delivery diagnostics | Medium / high |
| `InMemoryStateStore`, `JsonStateStore`, `RepoStateStore` | `get/put`: memory, file, or injected-repository state implementations | Medium / medium |
| `JsonlEpisodeStore`, `RepoEpisodeStore`, `RepoActionSink` | `append`: file writes or delegation to injected repositories | Medium / medium |

`AgentRuntime` methods group into input (`observe/accept_user`), context (`build_context`), callbacks (`record_reply/record_delivery/record_error`), execution (`dispatch_deferred/dispatch_proactive`), and transitions (`schedule_proactive/clear_proactive/clear_wait/claim_dispatch/schedule_retry/mark_delivered`). These still belong to one class; internal separation has not been implemented.

### ports: required external capabilities

Named protocols are listed by their existing roles, not as interchangeable contracts. Composition still owns connection, file path, cache, and background-task creation and cleanup.

| Protocol | Members | External responsibility |
| --- | --- | --- |
| `ChatModel` | `complete` | Provider-neutral request completion with text and usage |
| `Retriever` | `retrieve` | Candidates from a supplied memory pool |
| `SourceStore` | `append_sources/recent_sources/source_umo/source_umos/sources_by_ids` | Append immutable evidence; read evidence and originating sessions by time/ID |
| `ArtifactStore` | `get/by_source_ids/list/list_recent/list_impressions/count_impressions/count/history/inspect_record`; `commit/commit_many/add_edge/edges_between/edges_of/set_parent` | Memory revisions, evidence/ledger commits, graph maintenance; separate edge/parent calls are not one transaction |
| `TreeArtifactStore` | `get/commit/list/edges_of/add_edge/set_parent` | Six storage operations required by tree use cases |
| `ArtifactCache` | `version/load/put/get/active/by_level/by_subject/remove/size`, plus `artifacts` | Active-memory read model, updated only after commit |
| `TreeCache` | `get/put/by_level` | Three tree cache operations; a miss does not prove storage absence |
| `ExtractionStore` | `enqueue_extraction/pending_extractions/queue_counts/release_deferred/ready_extraction_ids/mark_extraction_succeeded/mark_extraction_failed` | Source queueing, success markers, failure/retry |
| `MetricsStore`, `LedgerStore` | `capacity_usage`; `entries/verify` | Capacity measurements and business-ledger reads/verification |
| `PersonaPacks`, `DreamJournal` | `catalog/read/save/remove`; `recent` | Persona pack management and recent daily-cycle reads |
| `Clock`, `SessionStateStore` | `__call__`; `get/put` | UTC epoch seconds and mutable session-state storage |
| `MemoryContextPort`, `ModelGateway` | `build_context`; `complete` | Read-only memory context and runtime model text calls |
| `MessageSender`, `ActionPort`, `ActionSink` | `send`; `execute`; `append` | Legacy text delivery, host action execution, content-free action audit |
| `ProactivePolicy`, `TopicSource` | `evaluate`; `candidates` | Pure proactive eligibility and read-only topics |
| `SourceSink`, `PendingSink`, `CheckpointSink` | `append_sources`; `add`; `record` | Runtime evidence writes, pending projections, hit intake |
| `EpisodeWriter`, `EpisodeSink` | `record`; `append` | Episode intake and persistence, at distinct stages |
| `TraceSink`, `TraceWriter` | `record`; `append` | Diagnostic event intake and row writes, not business audit |

The daily cycle uses six named callbacks: `FlushFn` (bounded extraction), `PendingFn` (pending count), `MaintainFn` (maintenance), `UsageFn` (cumulative model usage), `Log` (status output), and `DreamClock` (datetime). FlushFn is a callable protocol included in the 33 protocols above; the other five are type aliases. `DreamClock` aliases the existing `app.dream.Clock`; it differs from the runtime `Clock`, which returns floating-point seconds.

### Similar interfaces do not necessarily duplicate implementation

| Related interfaces or implementations | Assessment |
| --- | --- |
| `ArtifactStore` and `TreeArtifactStore`; `ArtifactCache` and `TreeCache`; `SourceStore` and `SourceSink` | The latter expresses a narrower requirement and can share one implementation; separate protocols do not require separate storage implementations |
| `ChatModel` and `ModelGateway` | Both call models but use different request shapes and usage reporting; inspect provider wiring before deciding whether to unify these two conventions |
| `EpisodeWriter`, `EpisodeRecorder`, `EpisodeSink` | A `record → record → append` chain; the middle class currently only forwards and has no independent business rule, so simplification is possible |
| `CheckpointManager.flush` and `core.strength.reinforce` | Both calculate weight increases, but the former also counts hits, caps weight, and commits revisions; establish one rule owner before replacing either implementation |

### External requirements not yet fully declared

Centralized entry points do not mean every dependency is normalized. The implementation still requires capabilities without complete named protocols or without using those protocols in parameter annotations:

| Consumer | Actual requirement | Current gap |
| --- | --- | --- |
| `DreamCycle.dreams` | `get/begin/finish/recent` | Typed as Any; `DreamJournal` covers only `recent`, not the full cycle journal |
| `budget_from_config`, `DreamCycle` | Configuration reader | Uses Callable; individual policies still read their own keys |
| `CheckpointManager.artifacts/cache` | Revision commit and cache get/put | Constructor parameters do not name protocols |
| `RunRecorder.cache` | Read memory by ID | Any does not state the minimum capability |
| `RepoStateStore/RepoEpisodeStore/RepoActionSink` | `get/put`, `append`, `append_action` | Injected repositories lack narrow protocol declarations |
| `RuntimeWorker` | Enablement, session list, run construction, interval/retry callbacks | Anonymous Callable types; understanding wiring requires reading its constructor |
| `RunTracer`, `ToolPolicy.filter_tool_set` | Event `get_extra/set_extra`; tool set `tools/remove_tool` | Host-shaped objects enter application implementations without an explicit seam |

## Commit and evidence constraints

ArtifactStore.commit requires expected_revision; commit_many is for version writes that must succeed atomically as a group. The ports describe behavior but do not implement I/O.

`TreeArtifactStore` and `TreeCache` are the narrow ports required by TreeService, also declared centrally in `app/ports.py`, with six storage methods and three cache methods implemented by `store/`. Core no longer declares or exports them. A cache miss does not prove storage absence, and cache `put` does not persist data; callers own connection and cache lifetimes.

CheckpointManager relies on callers to supply only Artifacts retained in the final context; it does not check actual injection. Repeated hits within cooldown are ignored, other hits accumulate pending commit, and reinforcement is later committed with an Artifact revision and StateEvent. Persona request construction and draft parsing do not select evidence, decide revision eligibility, or persist data; calling services own those decisions.

## Ownership of side effects

ChatModel is a stateless call port. app budget, flush, wake, and timing policies do not connect to a database or schedule host tasks. DreamCycle, CheckpointManager, and AgentRuntime coordinate external reads/writes. Existing file implementations in `runtime/state.py` and `episode.py` access the filesystem directly; RunTracer and tool filtering still manipulate host-shaped objects. SQL remains owned by store.

## Internal clarification order

Pure-policy relationships are reasonably clear: budget → batch selection; persona request construction → draft validation; attention/proactive policies → scheduling selection. They do not call models or maintain database transactions and can retain their present roles.

The following work is proposed, not implemented:

1. **Write-back and daily cycles:** clarify CheckpointManager pending, commit, and cache-recovery phases; distinguish DreamCycle extraction, maintenance, budget stops, and journal outcomes. Declare complete dependencies; decide whether they belong in services after the services inventory.
2. **Runtime transitions and execution:** AgentRuntime owns state transitions, model calls, sending, and write-back. Deferred and proactive paths separately coordinate generation, sending, and failures. Identify shared stages and distinct rules before choosing a shared implementation.
3. **Failure handoffs:** deferred Source/episode write-back after sending sits outside the model/send exception handler, while CheckpointManager.flush combines commit and cache update in one handler. Assign recovery responsibility separately for no commit, committed-but-cache-failed, and sent-but-write-back-failed outcomes.
4. **Storage and host adaptation:** state.py mixes decoding and three stores; episode.py mixes outcome classification with file/repository writes; actions.py mixes identity rules, audit, execution, and repository adaptation. Tracing and tool filtering depend on host-shaped objects. Compare with store/adapters ownership before moving implementations.
5. **State release and unused shapes:** RunRecorder deduplication collections and Checkpoint hit cooldown records have no per-item eviction, only instance lifetime. RecallRequest/RecallResult are not used by production recall. Establish retention and actual consumers before consolidating or deleting them.

No cycles were found among explicit app file imports; dynamic imports and runtime behavior require separate verification. Centralized interface entry points do not change the implementation locations or recovery responsibilities listed above.

Code entry points: [domain.py](../../../../app/domain.py), [ports.py](../../../../app/ports.py); runtime behavior is described in [Agent Runtime](runtime.md).

## Complete dependency declarations

`DreamRunStore` declares `get/begin/finish/recent` for the full daily journal lifecycle; the console still only requires `DreamJournal.recent`. `StateRepository`, `EpisodeRepository` and `ActionRepository` declare the raw repository capabilities needed by runtime adapters and are exported by `app.ports`. Checkpoint and RunRecorder storage/cache dependencies now use existing protocol annotations; this step changes neither implementation nor failure behavior.

## Checkpoint recovery

Checkpoint separates uncommitted hits from cache repairs. `flush()` returns only newly committed IDs; `pending()` counts the union of unfinished IDs. Successful commits consume their hit batch before cache work. Cache failures retry only the refresh from the latest persisted head, preventing duplicate reinforcement or stale replacement. Cache misses no longer discard hits for active persisted memories. Recovery is process-local; reinforcement coefficients, evidence and atomic revision commits are unchanged.

## Daily policy and journal outcomes

Internal `dream_policy.py` computes time/budget rules only; `DreamCycle` orders extraction, maintenance and journal writes. A failed journal finish returns `failed / journal_finish_failed` while preserving completed counts. Errors retain only stages and exception types; diagnostic callback failure does not change the business outcome. The daily journal is not a cross-process lock and resuming does not guarantee exactly-once maintenance.

## Runtime internal dependencies

`AgentRuntime` retains its existing caller-facing methods. Internal `transitions.py` copies state and computes changes without I/O; `dispatch.py` coordinates deferred/proactive work through explicit model, delivery, context, state and recorder dependencies. Dispatch never holds the whole runtime, and transitions do not import the facade. Path-specific prompts and failure rules remain separate.
