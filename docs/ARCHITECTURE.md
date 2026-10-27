# SeekMemory Architecture v4

## Core rule

Source is the only immutable truth. Artifact is a derived, versioned interpretation.

## Layers

```text
AstrBot events / cron / external input
        |
        v
main.py: entrypoint composition only (no function bodies)
        |
        v
adapters/astrbot_plugin.py: AstrBot dependency wiring and lifecycle
adapters/astrbot_hooks.py:  event mapping and handler registration
        |
        v
services/: application services (access, recall, ingest, capacity,
            maintenance, background scheduling, history import)
        |
        v
app/: host-agnostic DTOs, contracts, runtime and pure policy
        |
        v
core/: Source, Artifact, Strength, versioning, disclosure
        ^
        |
store/ perceive/ recall/ maintain/ adapters/: concrete ports
```

## Store composition

One SQLite file and one connection preserve cross-table transactions. `store/__init__.py` is a
thin composition root with no SQL. Domain repositories own their tables:

- `artifacts`: nodes, versions, evidence, edges, state events, ledger commit.
- `sources`: immutable Source append/read.
- `extraction`: extraction queue admission and retry state.
- `imports`: private ChatLab initialization task summaries, retry selection metadata,
  task–Source progress and bounded atomic Source/queue admission.
- `runtime_state` / `runtime_episodes`: mutable scheduler state and append-only audit.
- `dreams`: daily dream ledger.
- `metrics`: read-only capacity counters.

Repository modules share the `SqliteDatabase` connection; they never open independent files.

The administrator history-import boundary lives in `adapters/chatlab.py`,
`webui/import_files.py` and `services/import_service.py`. The AstrBot composition layer injects
`ChatLabReader` through the application `HistoryReader` port. It validates ChatLab v0.0.2
before admission, derives stable Source IDs from the confirmed target UMO and external
message ID, then uses `HistoryImportStore` to isolate and track the extraction queue.
Historical extraction calls the existing `IngestService` in strict non-triage mode;
the import-specific maintenance operation updates only evidence-qualified shared
`bot:self` persona data. Raw files and private retry mappings are retained only for the
documented retry window and never appear in task summaries.

## Persistent model

- Source: source_id, turn_id, session_id, speaker_id, role, content hash, at, reply_to.
- Artifact: Header adds subject_id; payload follows family validators.
- artifact_versions: append-only full snapshots keyed by (entity, revision).
- state_events: lightweight cognitive deltas before a checkpoint.
- ledger: one event per committed Artifact revision.

## Write invariants

1. Source is idempotent and append-only.
2. Artifact commit uses expected_revision CAS.
3. One transaction writes blob, node head, version, evidence and ledger.
4. Cache is a derived view and updates only after commit.
5. LLM calls never run inside a SQLite transaction.

## Read and disclosure

Recall reads from in-memory indexes. Disclosure is one universal score:

exposure = context_affinity * subject_fit * scope_prior * topic_fit * (1 - sensitivity)

Levels: full >= 0.55, paraphrase >= 0.18, hint >= 0.03, otherwise silence.
Paraphrase uses a generic safe sentence, never raw content or extractor tags. Scope is a continuous prior, not a visibility gate. Cross-session text is only injected as a direct quote when context/subject affinity is high enough.

Recall is memory-first. The normal Artifact retrieval/selection runs first. Only when
the selected Artifact count is below `min(2, recall_k)` and the query has recall intent
may `RecallService` run one bounded Source evidence query. It reads a recent global
Source window, ranks locally by character-bigram BM25 plus recency/session/speaker
signals, and uses Source ids only to discover active Artifacts through
`ArtifactStore.by_source_ids()`. Source ids are internal evidence; Source text is never
rendered, logged or assembled. The discovered Artifacts pass the existing visibility and
disclosure path and fill only the remaining recall capacity. Pinned persona/impression
does not gate Source evidence discovery. Cross-session Source text is never copied raw.
Clock/greeting/empty queries do not trigger the query.

## I/O targets

- Recall: zero SQL reads after warmup for the Artifact path; weak Artifact recall may
  use one bounded Source query and one `by_source_ids` batch.
- One user turn: append user and assistant Source rows; extraction commits a batch.
- Reinforcement: state_events in memory; checkpoint once per 30 minutes.
- SQLite is the first store; repository ports allow a later PostgreSQL adapter.

## Agent runtime boundary

AstrBot keeps generic chat history and tool-loop context. SeekMemory injects a protected system memory block through on_llm_request and captures assistant replies through on_llm_response. Extraction uses its own ChatModel port and does not reuse chat context.

## Retrieval extension

Retrieval follows the existing `app.ports.Retriever` protocol. `RetrievalCandidate` carries
activation and lexical signals. The default `GraphRetriever` remains seed/spread;
optional `HybridRetriever` preserves activation and adds normalized BM25 lexical evidence.

BM25 使用标准库字符 bigram 倒排索引，不调用模型或网络。正文/标签按 0.75/0.25 融合，
固定 `s/(s+8)` 归一化；仅以本次可见池计算 N、df 和平均长度。
插件入口持有长生命周期检索器，聊天与诊断共用；Cache.version 变化后重建派生索引。
`build_block(..., hybrid_retriever: Retriever | None = None)` 支持接口注入。
`bm25_enabled=true`，新配置 `bm25_weight=1.0`；select 函数默认权重 2.0 保留旧调用兼容。
BM25 本身无 SQL，现有 graph/source/history 路径仍可能查询 SQLite。
本次不包含本地向量实现，不新增 semantic 字段或依赖；后续边界记录在 ISSUE-0024。

## Token and call budgets

`app.budget.ContextBudget` owns the request-side injection budget and the Source
evidence recall switches. Defaults are `source_recall_enabled=true`,
`source_recall_hours=12`, and `source_recall_max_candidates=80`; the final assembled
block stays within `budget_chars`. `app.flush_policy.chunk_turns()` retains the original
turn-only `MAX_TOPIC_TURNS` behavior; there is no chunk token budget.

`IngestService` records exact `usage_in`/`usage_cached`/`usage_out` from each
`ChatResponse` on `WriteOutcome` and exposes a content-free cumulative
`usage_snapshot()`. `dream_max_calls` (default 12) is the primary Dream budget:
`IngestService.flush(..., max_calls=..., max_tokens=...)` checks both the remaining
call allowance and the actual token delta before every real extraction call, leaving
unstarted pending rows recoverable. `DreamCycle` passes both remaining budgets and
records budget/usage/stopped in the dream summary. `dream_token_budget` is a secondary
guard with at most one-call slack. Maintenance still runs for committed work.

Dream triage batches prepared topic chunks only within one session, using
`dream_batch_tokens` (default 6000) plus a reserved prompt estimate. The same-session
batching is a packing optimization: one batch is one real extraction call, a single
topic chunk is never split further, and cross-session batching is intentionally out of
scope because extraction evidence validation assumes one session. Multi-topic batches
add topic labels to the dialogue rendering and require every extracted item to cite
non-empty evidence IDs from a single topic; missing, invalid or cross-topic evidence is
retryable and lineage is never widened to every batch source. Single-topic batches keep
the original prompt format and legacy no-evidence fallback.

Dream extraction also runs deterministic, purely local importance triage before provider
resolution and model calls. Topics are grouped by session/topic and scored from user
memory signals plus behavior-relevant assistant replies only when a user turn is present,
using distinct category labels, then selected high-to-low at or above a fixed threshold.
First-person/possessive forms, personal date+action contexts and an assistance
command guard prevent bare date words, generic work terms, retrieval questions and
unrelated single-character family/pet mentions from spending calls. Low-value topics
remain pending and unmarked. Only Dream uses triage; normal nightly/idle extraction keeps
FIFO topic selection. Ranking happens once per flush. Paired user+assistant topics can
also score for bot behavior, and user corrections score directly, so behavior-relevant
replies can reach the existing self-impression path. Assistant-only topics and generic
courtesy remain low value; only behavior-relevant paired replies are converted, not every
bot message. The known tradeoff is narrower self-impression coverage because selection is
driven by user-memory value.

`benchmarks/dream_eval.py` measures that tradeoff on a frozen synthetic corpus through the
production `DreamCycle -> IngestService.flush` path, using an isolated in-memory SQLite store
and a deterministic recorded provider. It records calls, `usage_in`/`usage_cached`/`usage_out`,
triage seen/eligible/selected/skipped counts, artifacts, important-fact recall, modeled
false-memory and duplicate rates, bot-behavior/self-impression coverage, and pending count/age.
`benchmarks/dream_tradeoff.py` runs each checkout in its own process and records the `cc814ce`
baseline against `d9fc248` in `benchmarks/results/dream_tradeoff.md`. The harness never writes
Artifacts; `IngestService` remains the only extraction writer, and the fake provider is
evaluation-only.

All production writes use `artifacts.commit()` with expected revision, version snapshots,
evidence links and ledger entries. `ArtifactRepository.upsert()` is a seed/benchmark primitive,
not a production write path.

## Topic, subject and time

Buffer entries are typed `DialogueTurn` objects. Topics split on a 90-minute gap or low
character-bigram similarity; `topic_ttl_seconds` forces aged topics to extraction.
The extractor returns `subject_kind`, `subject_id`, `event_at` and validity dates.
`TimeSpan.created` uses event time, not extraction time.

## Current implementation status (v0.4.0)

- Source is persisted for both user and assistant messages, including group sessions.
- Production writes use CAS `artifacts.commit()` with versions, evidence and ledger.
- Topic-aware DialogueTurn buffer with 24h TTL extraction trigger.
- subject_kind/subject_id and event_at are part of extraction; Artifact created time is event time.
- Recall applies disclosure before assembly; cross-session text is never injected raw.
- Live validation: group sources and group Artifacts are being produced. A matching query selected
  two live Artifacts and applied paraphrase/silence disclosure.
- BM25 已接入，默认开启；实现及验收限制见 [ISSUE-0024](issues/ISSUE-0024.md)。
- Capacity governance is a pure `core/capacity.py` policy over Source, Pending,
  Artifact, Context and Trace metrics. Pending is rebuilt by joining
  `extraction_state` to immutable Source; it is not a second dialogue copy.
  The governor selects a state and bounded scheduler actions, while Source and
  Artifact history remain immutable/auditable.
- Under `backpressure` admission closes: new turns still persist their Source row
  but their extraction state is parked as `deferred`, and `release_deferred()`
  promotes them back once the governor returns to `normal`. Failed extractions
  back off and end in the terminal `dead` state instead of retrying forever.
- Non-Dream extraction batches rotate one topic per session. The scheduler keeps its own
  bounded `webui/trace.py` ring for capacity samples, separate from the
  business Journal event log.
- Not implemented yet: local vector retrieval, general reflection signals and full RBAC.

## Robot self-impressions (GitHub #15)

User and assistant turns keep `turn_id` and `reply_to` in the pending projection.
An assistant reply inherits the actual parent topic; extraction can read an already
processed immutable parent as context without re-queuing it. Per-item evidence
is checked before deduplication. A behavior scene references exactly one real
user/reply pair, so one batch or several artifacts cannot inflate its frequency.

Weekly/dream maintenance aggregates self-impressions before decay and merge.
It requires at least three distinct assistant Sources with confidence >= 0.9,
then creates or revises a `bot:self` impression. User impressions remain independent.
The six v1 behaviors are responding to emotion, clarifying, admitting uncertainty,
offering choices, protecting privacy and correcting mistakes. Shared text comes
from fixed generic sentences, never extracted names, places or private facts.

Persona keeps one stable id and append-only revisions. A persona file is a
one-time bootstrap into the initial `bot:self` persona revision: it carries
explicit seed provenance and an optional bounded authored style corpus, creates
no Source and runs no extraction. The initial revision may store the corpus for
authoring/audit; later Dream revisions keep only its count/hash. The corpus is
never injected into recall. After bootstrap, Dream synthesis may make an
incremental revision from the active persona text plus bounded self-impressions
and shared memory summaries. It is one optional model call per eligible
Dream cycle (default seven-day interval), with evidence lineage on the same
persona id. Persona
changes and any duplicate-head retirement commit atomically. Old unverified
persona text remains in history but cannot enter chat context. No model/network
call is added to chat capture or recall; behavior fields use the existing
background extraction call. The admin timeline shows each revision's own lineage
and protected dialogue evidence. See `docs/PERSONA_SEED.md`.

## Agent Runtime boundary

`app/runtime/` is host-agnostic and `AgentRuntime` is the single run-lifecycle hub.
`SessionState` is mutable per-session runtime state, `RunContext` is one inbound run,
`RunDecision` is one attention/timing decision, `RunResult` is its observed outcome, and
`EpisodeRecord` is the append-only business audit row. `TimingPolicy` owns pure time
decisions, `Scheduler` owns due-session selection from persisted session state, and
`WakePolicy` owns inbound-event attention only. `ModelGateway` and `MessageSender` are
host ports. `RunRecorder` is the single write-back service for user/assistant Source,
pending buffer and runtime episode records.

`services/` contains one service per application capability and a typed
`ServiceCollection`; it contains no DI container or registry:
`AccessPolicy` for permissions, `RecallService` for read assembly, `IngestService` for
pending-buffer extraction, `CapacityService` for admission and maintenance triggers, `MaintenanceService`
for decay/merge/persona work, `ManagementService` for admin queries,
`StatusService` for read-only status, `RuntimeWorker` for due dispatch, and `BackgroundService` for
periodic cadence. `main.py` is the entrypoint only. `adapters/astrbot_plugin.py` is the
AstrBot composition root and lifecycle owner; `adapters/astrbot_hooks.py` owns event
mapping and registers handlers against the real plugin module path. Neither layer may
construct Source rows, call `RunRecorder`, or contain extraction/capacity algorithms.

The gate is explicit. With `runtime_gate_enabled=false`, wait windows and deferred dispatch
are inactive; no runtime timer can cause a model call or message send. With the gate enabled,
deferred replies use the host provider directly; they do not run the full AstrBot tool loop.
Proactive generation remains a future feature.

## Runtime active path (v0.4.0)

The runtime has two production paths, and every retained runtime type must be reachable from one of them.

### Normal reply

```text
AstrBot message event
-> AstrBotHooks maps RuntimeInput
-> AgentRuntime.accept_user()
-> RunRecorder.record_user()/Buffer Source projection
-> AgentRuntime.observe()
-> optional event.should_call_llm() gate
-> MemoryContextPort / RecallService
-> AstrBot model request
-> capture_reply()
-> AgentRuntime.record_reply()
-> after_message_sent()
-> AgentRuntime.record_delivery()
-> RunRecorder delivery episode + SessionState delivery transition
```

### Deferred ambient reply

```text
runtime state with wait deadline
-> RuntimeWorker.tick()
-> Scheduler + TimingPolicy
-> AgentRuntime.dispatch_deferred(RunContext)
-> claim_dispatch()
-> ModelGateway.complete()
-> MessageSender.send()
-> RunRecorder.record_deferred_reply()
-> assistant Source + extraction buffer
-> EpisodeRecord
```

### Explicit boundaries

- Proactive generation is not implemented and has no scheduling path yet.
- `ToolPolicy.filter_tool_set()` filters `req.func_tool` before the model sees tools; the advisory
  `on_using_llm_tool` trace is not a veto.
- `RunRecorder` owns assistant Source, pending-buffer and episode write-back. Run id is the
  idempotency boundary so repeated callbacks cannot duplicate those writes.
- `RunTrace` is an admin observability stream, separate from the append-only runtime
  episode audit. It is not an Artifact or Source.
- `runtime_gate_enabled=false` keeps both wait and deferred dispatch inactive.

Cleanup rule: a runtime module or protocol without a production caller is either removed or
explicitly marked as a documented seam. Tests alone are not a reason to keep a production abstraction.

## Policy ownership

- `WakePolicy` owns inbound-event attention only; it does not duplicate timing decisions.
- `TimingPolicy` owns pure wait/retry deadline evaluation; inbound quiet/cooldown attention
  stays in `WakePolicy`.
- `Scheduler` owns querying persisted session state and reporting due runs. It does not send,
  generate, or mutate state.
- `ToolPolicy` owns both the enforced `req.func_tool` filter and the advisory tool-call trace.
  There is no second guard object for the same decision.
- `RunRecorder` owns completed-run write-back; `main.py` must not write assistant Source or
  episodes directly.
- `AgentRuntime` owns both normal-run transitions (`accept_user`, `record_reply`,
  `record_delivery`, `record_error`) and the deferred lifecycle (`dispatch_deferred`).
  `RuntimeWorker` owns due polling and in-flight dedupe; `AstrBotPlugin` only maps session
  state to a `RunContext` through its composition callback.
- `AgentRuntime` exposes only production transitions: observe, context build, wait clearing,
  dispatch claim, retry scheduling and delivery marking. Test-only mutation helpers are not
  part of the runtime API.
