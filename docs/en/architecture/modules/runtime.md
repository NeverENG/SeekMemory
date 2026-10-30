# Agent Runtime: Session Attention and Runtime Actions

## Responsibility

app/runtime defines host-agnostic session state, attention decisions, and runtime action lifecycle. It coordinates when to observe, reply, or wait, including deferred replies. It does not replace SeekMemory extraction/recall or AstrBot's ordinary agent/tool loop.

## Objects and policies

- RuntimeInput is a reduced host event; RunContext is one pending action context.
- SessionState stores runtime scheduling state such as wait, retry, quiet, proactive, unread/read-through, and dispatch attempts. It is not a Source or Artifact.
- `DefaultAttentionPolicy` only decides whether to reply: the owner, private messages, and direct attention reply; after a non-owner direct interaction, a three-round per-speaker follow-up window is retained; other messages are observed. It contains no group, relationship, heat, or quota policy.
- TimingPolicy is a pure wait/retry deadline policy. Scheduler reads persisted state and returns due runs; RuntimeWorker polls, deduplicates in-flight work, and dispatches without owning memory rules.
- MemoryContextPort delegates to the existing RecallService through an adapter; Runtime does not implement a second memory retrieval path.
- ActionPort accepts transient ActionRequest (session_id, kind, text) and returns ActionResult (ok, reason). MessageSender retains its boolean send interface; ActionRecord remains content-free audit metadata, and execution results do not decide audit terminal states.

## Proactive policy and action audit

`DefaultProactivePolicy` is a deterministic, state-only policy. It requires an explicit `now`, returns the next eligibility time, and applies the due time, quiet deadline, cooldown, retry delay, ignored-streak backoff, and attempt limit. It performs no I/O, model call, or state mutation; it is disabled by default until runtime composition opts in. `plan_proactive_dispatch` sorts eligible sessions by due time, applies a per-tick fan-out cap, and returns overflow as still-due work for later ticks. Hosts persist an explicit due time through `AgentRuntime.schedule_proactive()`; when proactive is enabled, the AstrBot message entry point schedules it from `proactive_idle_seconds`. `TopicSource` derives memory reasons from the Source-backed buffer projection; when no candidate exists, the worker clears that opportunity instead of sending an empty proactive message.

`ActionExecutor` is the sole execution/audit coordinator for runtime-originated actions: it records the attempt, calls `ActionPort`, then records the terminal outcome; `ActionMessageSender` is only a compatibility `SEND_TEXT` adapter. `ActionLedger` records an attempted action followed by at most one terminal outcome (`succeeded`, `failed`, or `cancelled`). Its stable idempotency key is derived from session, run, action kind, and the host callback key; the callback key itself is not stored. `RepoActionSink` writes metadata through `RuntimeEpisodeRepository`. The audit stores only identifiers, timestamps, bounded reason codes, attempt numbers, and status; it excludes message text, prompts, tool arguments, and results.

`SessionState` stores session scheduling state and a per-speaker `followup_by_speaker` counter. It is not a memory subject; speaker identity remains in `speaker_id`.

## Two runtime paths

**Normal AstrBot reply:** a hook gives the user message to AgentRuntime.accept_user; RunRecorder writes a user Source and queue projection; the request hook gets memory through runtime.build_context; after model response and host delivery, capture/delivery hooks use AgentRuntime and RunRecorder to record the assistant Source, recall reinforcement, and EpisodeRecord.

UserRunReceipt from accept_user includes the read_through_seq acknowledgement cursor captured for that run. The host carries it on the event and returns it to record_delivery after sending. Runtime acknowledges only messages through that cursor and preserves later unread input and scheduled work. Duplicate or out-of-order acknowledgements cannot move the read cursor or last delivery time backwards. Legacy calls without a cursor and stale events update delivery timing only. The extraction queue is not an unread counter; the host does not infer session unread counts from its length.

**Deferred ambient reply:** when runtime_gate_enabled is on, the worker selects a session whose wait/retry deadline is due. Runtime claims dispatch, builds memory context, calls ModelGateway, sends through MessageSender, then records the assistant Source and EpisodeRecord. Failure uses bounded per-session retries with exponential backoff. This path calls the provider directly and does not run the full AstrBot agent/tool loop.

Wait/retry deadlines remain persisted during model and send calls, with attempts persisted before the call. Cancellation schedules bounded retry and propagates cancellation. After process loss, the existing Scheduler can recover from that same state. Attempts survive restart, and a new Source has its own attempt budget. Only successful acknowledgement or exhaustion clears the corresponding work; deadlines installed by newer input are preserved. Runtime keeps a claim-time state snapshot to distinguish retained markers from newer work, without adding database fields, tables, or another scheduling loop.

After confirmed send success, runtime refreshes the injected clock for delivery audit and last delivery time. Failure or cancellation also refreshes the clock so backoff starts at failure time. An explicit now is a lower bound for that run. RuntimeWorker.dispatch owns the shared concurrency limit and session deduplication for both scans and direct calls. Queued sessions remain deduplicated; after acquiring a slot, dispatch rechecks the gate, clock, and due state. Cancellation releases both the slot and session marker. Coordination applies to one worker process and does not guarantee exactly-once sends across processes.

runtime_gate_enabled defaults to false. While disabled, wait and background deferred dispatch are inactive; ordinary event capture, memory injection, and audit hooks remain available.

## Write-back and diagnostics

RunRecorder is the single runtime write-back coordinator for Sources, pending projection, checkpoint, and episodes. run_id and deterministic Source IDs prevent repeated callbacks from duplicating writes. runtime_episodes is append-only business audit metadata; RunTracer/TraceStore is a field-whitelisted diagnostic timeline. They are separate and neither stores conversation bodies.

Completed user receipts and pending user writeback use the existing Source ID as their internal key, preserving session, speaker, and text identity boundaries. Sessions may reuse event IDs, while exact message replays remain idempotent. Public turn_id values retain the original event_id, or the Source ID when absent.

### Run trace event boundary

RunTracer in `app/runtime/tracing.py` is a host-neutral producer; events need only get_extra/set_extra for correlation. `core/trace.py` owns field cleaning and run projection; `store/run_trace.py` owns JSONL persistence. Management queries consume the same snapshot; see [WebUI](webui.md#run-trace-queries).

| Event | Observation |
|---|---|
| `agent_begin` | Run begins with a randomly generated run_id |
| `llm_request` / `llm_response` | Request index, allowlisted recall summary and available timing; no model input/output |
| `tool_call` / `tool_result` | Tool name and available timing; no arguments or result body; unknown outcomes remain unknown |
| `agent_done` | Run completion status |
| `message_sent` | Observed successful delivery, independent of memory injection |

Public event fields are limited to run_id, sequence, at, event, request_index, status, duration_ms, tool, and recall. Recall retains only bounded generated IDs, counts, fixed mode/fallback/disclosure enums and gate numbers. It excludes messages, prompts, responses, Source text, tool arguments/results, user/session identifiers and credentials. Write and reload both remove unknown fields. Event statuses are running/ok/error/unknown. Existing projection yields error for an erroneous completion, completed for other completion or successful delivery, interrupted for unfinished runs preceding startup, and running otherwise.

TraceStore defaults to seven days and at most 5,000 events. Producers remove expired or excess records. Diagnostic write failures do not block the main operation; persistence_error warns that records may be incomplete. Missing or evicted events do not prove a step never ran. The standalone console loads offline files read-only at startup; replacing the snapshot requires a restart. It must not share a data directory with a running host.

ToolPolicy can remove disallowed tools from req.func_tool before the model request. A post-call tool observation hook is diagnostic and cannot block execution by itself. Actual request filtering is controlled by runtime_tool_filter_enabled and is disabled by default.

## Write-back after delivery

Runtime retains a process-local receipt immediately after confirmed sending. Session acknowledgement, Source/projection and audit complete in stages; failures return `RunResult(delivered=True, error="writeback_pending")` without generating or sending again. `AgentRuntime.retry_writebacks()` returns completed write-back items. The worker calls it before checking speaking enablement and again on shutdown. Unfinished session delivery blocks new background sends while normal input remains accepted. Even when normal reply persistence fails, prepared identity remains available to bind host delivery; the callback acknowledges state before retrying Source and audit.

RunRecorder retains completion positions for Source, projection and individual reinforcement IDs, retrying only missing stages. New repository audit IDs derive from session/run identity; historical rows remain unchanged. State read errors no longer masquerade as empty sessions; state/audit writes retain last_error and raise so orchestration can retry. Diagnostics remain isolated. Failed file replacement preserves both durable and cached old state.

Receipts and compensation are not durable across processes. Crashes and unknown send outcomes may still trigger retries; this is not an exactly-once delivery guarantee across restarts.

## Internal files and resources

The facade remains in runtime.py; transitions.py computes detached state only, dispatch.py executes background work through ports, and writeback.py manages confirmed-delivery recovery. These do not import AgentRuntime. recorder.py remains the single Source/projection/reinforcement/audit coordinator. Existing state/episode/action storage adapters, host tracing and tool filtering remain in place. Source comments use English followed by equivalent Chinese; the app module page inventories interfaces.

File audit retries recognize complete saved rows through existing `session_id/run_id` fields. An uncertain append reloads persisted identities before retrying. This covers a single instance and complete rows seen by a new instance, not cross-process file locking, and adds no file fields.

Memory context construction uses the pure `RecallService.query()`. Explicit inclusion recording is forwarded through the optional generic `MemoryContextRecorder`; ordinary host hooks call it after request attachment, background dispatch immediately before model invocation. The runtime contains no designated rules. Existing `RecallService.build()` remains a compatibility query-plus-recording entry.
