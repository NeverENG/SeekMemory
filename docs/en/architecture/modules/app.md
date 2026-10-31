# app: Ports, DTOs, and Application Policies

## Responsibility

app provides shared application values, external capability declarations, and policies. It currently also contains daily-cycle coordination, reinforcement write-back, runtime execution, and some persistence adapters; the directory as a whole is not a pure policy layer.

## Configuration ownership

Host-neutral `app/config/` owns defaults grouped by project, ingest, recall, Dream, maintenance, attention, proactive, observability, relationship, and Runtime. An empty configuration is supported; AstrBot’s `_conf_schema.json` remains a compatibility input and UI projection of existing keys, not the owner of defaults. Console uses the same entry point. Services still pass legacy fallbacks during incremental migration; subsequent changes must preserve existing default behavior.

`app/config/catalog.py` inventories each existing key by group, basic/advanced/internal level and stability. This is classification, not an AstrBot UI or behavior change. “Internal” means not recommended as a normal user-facing tuning option; existing public keys remain accepted for compatibility.

`app/config/runtime.py` provides a typed, immutable snapshot of Runtime scheduling options. Startup determines the wait duration; the worker re-reads options when polling to retain the existing live-override behavior.

## Two interface entry points

- [app/domain.py](../../../../app/domain.py): what the application provides. It explicitly exports 79 types, functions, and execution classes, with descriptions only; implementations remain in their owning files.
- [app/ports.py](../../../../app/ports.py): what callers must supply. It explicitly lists required protocols and callback type aliases, with declarations or exports only and no I/O implementation.

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
| `MemoryContextRequest`, `MemoryContext` | Read-only memory context input/output | `app/runtime/contracts/context.py` |
| `ActionKind`, `ActionStatus`, `ActionRequest`, `ActionResult`, `ActionRecord` | Action vocabulary, execution input/output, content-free audit | `app/runtime/contracts/actions.py` |
| `RecordedTurn`, `RecordedReply` | Identity/counts after Source write-back | `app/runtime/recorder.py` |
| `ProactiveCandidate`, `ProactiveDispatchPlan`, `DueRun`, `TopicCandidate` | Proactive selection, due work, topic candidate | `app/runtime/policy/proactive.py`, `scheduler.py`, `topics.py` |
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

`AgentRuntime` methods group into input (`observe/accept_user`), context (`build_context`), callbacks (`record_reply/record_delivery/record_error`), execution (`dispatch_deferred/dispatch_proactive`), and transitions (`schedule_proactive/clear_proactive/clear_wait/claim_dispatch/schedule_retry/mark_delivered`). These remain compatibility methods. Pure state calculation now lives in internal transitions, background execution in dispatch, and process-local delivery recovery in writeback. The new `retry_writebacks()` retries writes only, with no model or sender access.

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
| `DreamRunStore` | `get/begin/finish/recent` | Complete daily journal lifecycle with observable failures |
| `StateRepository`, `EpisodeRepository`, `ActionRepository` | `get/put`; `append`; `append_action` | Raw repository slots for runtime adapters, without SQL |
| `PersonaPacks`, `DreamJournal` | `catalog/read/bundle/artwork/save/remove`; `recent` | Persona pack management and recent daily-cycle reads |
| `Clock`, `SessionStateStore` | `__call__`; `get/put` | UTC epoch seconds and mutable session-state storage |
| `MemoryContextPort`, `ModelGateway` | `build_context`; `complete` | Read-only memory context and runtime model text calls |
| `MessageSender`, `ActionPort`, `ActionSink` | `send`; `execute`; `append` | Legacy text delivery, host action execution, content-free action audit |
| `ProactivePolicy`, `TopicSource` | `evaluate`; `candidates` | Pure proactive eligibility and read-only topics |
| `SourceSink`, `PendingSink`, `CheckpointSink` | `append_sources`; `add`; `record` | Runtime evidence writes, pending projections, hit intake |
| `EpisodeWriter`, `EpisodeSink` | `record`; `append` | Episode intake and persistence, at distinct stages |
| `TraceSink`, `TraceWriter` | `record`; `append` | Diagnostic event intake and row writes, not business audit |

The daily cycle uses six named callbacks: `FlushFn` (bounded extraction), `PendingFn` (pending count), `MaintainFn` (maintenance), `UsageFn` (cumulative model usage), `Log` (status output), and `DreamClock` (datetime). FlushFn is a callable protocol included among the protocols above; the other five are type aliases. `DreamClock` aliases the existing `app.dream.Clock`; it differs from the runtime `Clock`, which returns floating-point seconds.

### Similar interfaces do not necessarily duplicate implementation

| Related interfaces or implementations | Assessment |
| --- | --- |
| `ArtifactStore` and `TreeArtifactStore`; `ArtifactCache` and `TreeCache`; `SourceStore` and `SourceSink` | The latter expresses a narrower requirement and can share one implementation; separate protocols do not require separate storage implementations |
| `ChatModel` and `ModelGateway` | Both call models but use different request shapes and usage reporting; inspect provider wiring before deciding whether to unify these two conventions |
| `EpisodeWriter`, `EpisodeRecorder`, `EpisodeSink` | A `record → record → append` chain; the middle class currently only forwards and has no independent business rule, so simplification is possible |
| `CheckpointManager.flush` and `core.strength.reinforce` | Both calculate weight increases, but the former also counts hits, caps weight, and commits revisions; establish one rule owner before replacing either implementation |

### External dependency status

Centralized entry points do not mean every dependency is normalized. The following lists completed declarations and dependencies still awaiting later inventory:

| Consumer | Actual requirement | Current gap |
| --- | --- | --- |
| `DreamCycle.dreams` | `get/begin/finish/recent` | Uses `DreamRunStore`; the console still only requires `DreamJournal.recent` |
| `budget_from_config`, `DreamCycle` | Configuration reader | Uses Callable; individual policies still read their own keys |
| `CheckpointManager.artifacts/cache` | Revision commit and cache get/put | Uses existing `ArtifactStore` and `ArtifactCache` |
| `RunRecorder.cache` | Read memory by ID | Uses existing `ArtifactCache`; further narrowing awaits caller inventory |
| `RepoStateStore/RepoEpisodeStore/RepoActionSink` | `get/put`, `append`, `append_action` | Uses `StateRepository`, `EpisodeRepository` and `ActionRepository` |
| `RuntimeWorker` | Enablement, session list, run construction, interval/retry callbacks | Anonymous Callable types; understanding wiring requires reading its constructor |
| `RunTracer`, `ToolPolicy.filter_tool_set` | Event `get_extra/set_extra`; tool set `tools/remove_tool` | Host-shaped objects enter application implementations without an explicit seam |

## Commit and evidence constraints

ArtifactStore.commit requires expected_revision; commit_many is for version writes that must succeed atomically as a group. The ports describe behavior but do not implement I/O.

`TreeArtifactStore` and `TreeCache` are the narrow ports required by TreeService, also declared centrally in `app/ports.py`, with six storage methods and three cache methods implemented by `store/`. Core no longer declares or exports them. A cache miss does not prove storage absence, and cache `put` does not persist data; callers own connection and cache lifetimes.

CheckpointManager relies on callers to supply only Artifacts retained in the final context; it does not check actual injection. Repeated hits within cooldown are ignored, other hits accumulate pending commit, and reinforcement is later committed with an Artifact revision and StateEvent. Persona request construction and draft parsing do not select evidence, decide revision eligibility, or persist data; calling services own those decisions.

## Ownership of side effects

ChatModel is a stateless call port. app budget, flush, wake, and timing policies do not connect to a database or schedule host tasks. DreamCycle, CheckpointManager, and AgentRuntime coordinate external reads/writes. Existing file implementations in `runtime/state.py` and `episode.py` access the filesystem directly; RunTracer and tool filtering still manipulate host-shaped objects. SQL remains owned by store.

## Logic and file layers

| Layer | Files | Responsibility and limits |
| --- | --- | --- |
| Interfaces and data | `domain.py`, `ports.py`; `contracts.py`, `console_ports.py`, `runtime/contracts/` | Two central entries declare/export/describe only; existing data/protocol definition paths remain compatible |
| Pure rules | `budget.py`, `flush_policy.py`, `persona_synthesis.py`, `dream_policy.py`; runtime attention, proactive, transitions and topic ranking | Compute from supplied inputs without models, persistence or clock reads |
| Orchestration | `checkpoint.py`, `dream.py`; runtime facade, dispatch, writeback, recorder, scheduler, worker and action execution | Read/write through injected capabilities; distinguish claims, generation, sending, acknowledgement, recording and compensation |
| External adapters | Existing state, episode and action storage implementations, tracing and tool filtering | Remain in place for now; composition owns connections, file paths and task lifetime, and SQL stays in store |

Internal direction is `AgentRuntime → Dispatch / DeliveryWritebacks → transitions / RunRecorder / external ports`. Pure transitions do not import the facade; dispatch never holds the whole Runtime. Scheduling selects read-only work, while the worker owns in-process concurrency/session guards and retries writes on its existing loop. Background paths retain distinct prompts and failure rules. The longer dispatch implementation retains both complete flows instead of dispersing orchestration across many callbacks.

## Commit and delivery recovery

| Stage | Failure and recovery owner |
| --- | --- |
| Reinforcement commit fails | Keep uncommitted hits, do not touch cache; retry on a later flush |
| Reinforcement commits but cache fails | Do not reinforce the same batch again; separately refresh from the latest persisted head |
| Model or sending fails | Retain bounded retry and cancellation propagation; a False send result is also failure |
| Sending is confirmed but state/recording fails | Retain a process-local receipt and return `delivered=True / writeback_pending`; retry missing writes only |
| Daily journal finish fails | Return `failed / journal_finish_failed` with completed counts, without rolling back earlier memory commits |

`CheckpointManager.flush()` counts new commits only; `pending()` counts distinct IDs in the union of uncommitted hits and cache repairs. New hits remain separate during repair. Cache absence does not prove database deletion.

`RunRecorder` tracks Source, projection, individual reinforcement and audit completion. `AgentRuntime.retry_writebacks()` returns completed write-back items without generating or sending; the worker calls it before speaking enablement and at shutdown. Unfinished session delivery blocks new background speech while normal input remains accepted. Normal reply persistence failures retain prepared identity for host delivery correlation; callbacks acknowledge the bounded read cursor before retrying reply/audit, and stale callbacks or recovery do not clear newer work.

State read errors do not masquerade as empty sessions. State/audit write failures retain `last_error` and raise for orchestration to retry; file state is published in memory only after successful replacement. New repository audit IDs are stable; historical records, schema and public configuration remain compatible. Diagnostics do not change outcomes and exception bodies are omitted.

Receipts and compensation live only in the current process, so crashes, unknown send results and multiple processes are not exactly-once delivery scenarios. The daily journal is not a distributed lock, and resumption does not guarantee exactly-once maintenance. Timezone conversion remains in adapters.

## Comments and verification entries

All app modules and public definitions use English followed by equivalent Chinese. Short descriptions use one line; longer descriptions explain responsibility, effects, resource ownership and failures. Machine directives, field values and prompts are not translated.

| Scenario | Existing verification entry |
| --- | --- |
| Public contracts and dependency exports | `tests/test_public_interfaces.py`, `tests/test_runtime_contracts.py` |
| Reinforcement commits and latest-head cache recovery | `tests/test_reinforcement.py` |
| Daily eligibility, budgets, journal and diagnostic failures | `tests/test_dream.py`, `tests/test_dream_eval.py` |
| Partial Source/projection/reinforcement recording | `tests/test_run_recorder.py` |
| Post-delivery failures, shutdown/disabled-speaking retry and storage failure | `tests/test_runtime_writeback.py` |
| Read acknowledgement, new-input protection and restart recovery | `tests/test_runtime_delivery.py`, `tests/test_runtime_recovery.py` |
| Concurrency, proactive policy and host wiring | Runtime scheduler/worker/proactive and host tests |

## Remaining work

- After the services/store/adapters inventory, retain current app storage adapters, EpisodeRecorder and perceive ProviderChatModel: relocation would change compatible paths or introduce reverse dependencies. Composition owns their resources; no additional migration is included.
- Deduplication results, completed compensation results and hit cooldown entries still live for the instance without defined retention; pending compensation may retain text in memory.
- `RecallRequest/RecallResult` remain outside production recall; `ChatModel/ModelGateway` still have distinct contracts.
- Worker configuration callbacks remain Callable; tracing and tool filtering retain host-shaped objects pending later movement.

Code entries: [domain.py](../../../../app/domain.py), [ports.py](../../../../app/ports.py); delivery contracts are described in [Agent Runtime](runtime.md).

Extraction callbacks may raise `ExtractionFailure` with completed write/topic counts. Dream retains those counts in its failed result and journal; the callback still owns prepared persistence recovery.

Memory context construction uses the pure `RecallService.query()`. Explicit inclusion recording is forwarded through the optional generic `MemoryContextRecorder`; ordinary host hooks call it after request attachment, background dispatch immediately before model invocation. The runtime contains no designated rules. Existing `RecallService.build()` remains a compatibility query-plus-recording entry.

## Shared rules and committed-ID repair

`cache_repair.py` owns only committed IDs, ownership labels and mark generations. It reads current database heads and refreshes/removes cache entries; it never commits memory or owns a business plan. Composition injects one shared `CacheRepairs` into checkpoint, ingest, context and maintenance writers. Each use case retains its own unfinished semantic plan; per-owner ID views preserve checkpoint `pending()` accounting. A same-ID mark during repair survives for the next attempt, avoiding loss of later work. Cache/connection construction and shutdown remain with composition.

`text_rules.py` owns proven-equivalent alphanumeric bigrams (single-character input preserved) and word-character bigrams/Jaccard (underscore behavior preserved) as distinct rules. `recall.seed` and maintenance compatibility paths retain aliases. No Dice/Jaccard or differently normalized rules are merged. `value_codec.py` owns the identical management/status legacy-object decoder. `revision_plan.py` reads the current head and prepares the identical Tree/legacy-persist replacement; parent/edge writes remain separate. The existing merge default lives in merge policy, and checkpoint reuses the domain hit increment without merging unrelated equal values.

Shared helper equivalence was checked against the pre-change implementations on 207 fixed/randomized inputs per matching variant; existing behavioral tests remain authoritative. `tests/test_cache_repair_integration.py` covers shared-ID deduplication, owner counts, continuous failures and reentrant same-ID marks. Existing app persistence adapters and the provider wrapper remain at compatibility-safe paths because relocation would create reverse imports.
