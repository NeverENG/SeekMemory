# adapters: AstrBot Host Integration

## Responsibility

adapters translates AstrBot events, providers, and message sending into application ports. Host objects do not leak into core, recall, or app/runtime domain policies.

## Composition root

On start, AstrBotPlugin builds Store, Cache, TreeService, Graph, HybridRetriever, Source-backed Buffer, CheckpointManager, application services, AgentRuntime, Jobs, WebRoutes, and background services. On stop, it stops background and management tasks, unregisters its own routes, saves the buffer, flushes checkpoints, and finally closes Store.

main.py defines the plugin entry point and delegates lifecycle; composition and wiring live in adapters/astrbot/plugin.py. AstrBotPlugin explicitly owns hooks and attention components instead of sharing host state through multiple inheritance. AstrBotHooks in adapters/astrbot/hooks.py maps host hooks to service calls: access decisions, input acceptance, memory injection, assistant-reply capture, post-send delivery recording, and runtime/tool observation. It does not implement extraction, capacity, or maintenance algorithms.

Start and stop share a lifecycle lock. Partial initialization releases resources already created. Shutdown waits for background and management tasks before saving buffers, flushing checkpoints, and closing storage, then clears services, workers, caches, and host references. Cancellation waits for cleanup before propagating, allowing a safe restart.

## Port adapters

- AstrBotRuntimeAdapter reuses astrbot.events.to_runtime_input, preserving existing scene, role, addressed, thread, and message-ID fields, and manages event-extra values for user/reply Source IDs, turn IDs, final recall IDs, and episode deduplication. Event time and process receipt time are recorded separately.
- AstrBotModelGateway provides ModelGateway for deferred replies.
- AstrBotActionPort provides both ActionPort and MessageSender: execute accepts ActionRequest and returns ActionResult; the existing send method delegates to execute and returns a boolean.
- ProviderChatModel wraps a host extraction/persona provider as ChatModel.
- SeekMemoryContextAdapter connects Runtime's MemoryContextPort to the existing RecallService.
- RelationshipInteractionPolicy reads one validated per-subject Relationship snapshot from Cache and converts the existing Runtime decision plus the recorded Source ID into a content-free InteractionGate. AstrBot hooks enforce denial and append fixed style directives without adding relationship semantics to app/runtime.

Action request text is transient execution input, never an ActionRecord audit field. Unsupported actions return unsupported_action; empty text, missing sessions, unavailable hosts, rejected sends, and execution errors have fixed reason codes. Host exception messages are not returned; cancellation propagates so runtime can recover. The adapter reports execution results without owning retries, audit deduplication, or terminal-state decisions.

AstrBot centralizes time conversion in utc8_time_hook in astrbot/time.py. User messages, normal replies, deferred replies, and runtime audit pass through this adapter hook before calling the existing RunRecorder. New timestamps use ISO strings with an explicit +08:00 offset; kernel read views retain the existing naive format. Fields, kernel interfaces, and database structure are unchanged.

AstrBotBuffer reuses Buffer admission and topic algorithms, while AstrBotSourceView reuses SourceStore queries. Both use the same hook for pending projections and recovered processed parents. Historical Sources are not rewritten. Offset-aware legacy values are converted; missing, invalid, and offset-free values are preserved without guessing the old machine's timezone or deriving absolute event time or queue age from them. Whether those old values were wrong, or derived memories need revision, requires a separate audit against the original environment.

Runtime decisions still use epoch timestamps independently of the OS timezone. Time adaptation does not change core, Buffer, extraction contracts, or nightly-maintenance scheduling configuration.

AccessService uses full session UMO, sender ID, owner/trusted configuration, and observe_groups to decide whether a message can be observed/recalled. Host event details are normalized only at this boundary; plugin composition owns config and database path.

## Current boundaries

Hook registration must use the real plugin module path, so callbacks stay discoverable after reload. Runtime tool filtering runs before a model request; a tool observation hook after invocation is not enforcement. Host API limitations and plugin startup failures are handled at the outer boundary and must not leak AstrBot dependencies into business modules.

Relationship denial is enforced independently of the opt-in base Runtime gate; an allowed or neutral relationship never enables that gate. Low/dislike ordinary private statements use stable `0.8`/`0.5` Source-ID sampling, while actual questions and direct host signals remain required replies. Low/dislike group ambient is denied. Relationship Artifacts remain excluded from Recall and the management catalog.

## DSH runtime bridge

DSH RuntimeBridge reuses KernelClient's authenticated loopback connection. After healthz advertises runtime_contract: 1, POST /runtime/events carries inputs, replies, deliveries, errors, and action execution results; POST /runtime/context obtains MemoryContext. app/runtime/contracts/ owns the public fields, and Python and Node both validate shared nonempty examples. Known millisecond or offset-aware event times map to epoch seconds; unknown time is 0 without guessing a historical timezone.

subject_key identifies stable memory ownership, while session_id identifies the runtime conversation. Pre-step uses a Source receipt and event time only when the message ID matches. Only an explicit server runtime_gate_enabled enables mapping its RunDecision to host admission or rejection; the bridge has no separate attention policy.

Legacy or unsupported runtime services retain capture/recall. Once a runtime write is attempted, failure or timeout never triggers a legacy capture, preventing duplicate writes. An ordinary assistant/message maps only to record_reply; without confirmed delivery it does not call record_delivery. The bridge adds no model loop, scheduler, proactive sender, or tool execution. `scripts/runtime_http.py` is a composition-only real Python loopback service; `runtime-python-smoke.mjs` starts it and drives the DSH RuntimeBridge against the real AgentRuntime.

Each DSH host context registers once. Unload removes hooks, aborts bridge requests, and clears context caches; late responses cannot inject. The repository now also contains a real Python loopback composition (`scripts/runtime_http.py`) and a Node test that exercises the DSH bridge against it.
Relationship mode defaults to observe: RelationshipInteractionPolicy may compute a content-free candidate interaction profile, but it does not inject directives or deny replies by default. Reply denial requires both explicit `relationship_mode=enforce` and the existing `runtime_gate_enabled=true`; an allowed or neutral relationship never enables that gate. Low/dislike ordinary private statements use stable `0.8`/`0.5` Source-ID sampling when enforcement is explicitly enabled, while actual questions and direct host signals remain required replies. Low/dislike group ambient is denied under the same explicit enforcement controls. Relationship Artifacts remain excluded from Recall and the management catalog.
Relationship mode defaults to observe: RelationshipInteractionPolicy may compute a content-free candidate interaction profile, but it does not inject directives or deny replies by default. Reply denial requires both explicit `relationship_mode=enforce` and the existing `runtime_gate_enabled=true`; an allowed or neutral relationship never enables that gate. Low/dislike ordinary private statements use stable `0.8`/`0.5` Source-ID sampling when enforcement is explicitly enabled, while actual questions and direct host signals remain required replies. Low/dislike group ambient is denied under the same explicit enforcement controls. Relationship Artifacts remain excluded from Recall and the management catalog.

## Explicit interfaces and host bindings

`adapters/domain.py` exports SDK-free shared persona-file and relationship adapters; `adapters/ports.py` reuses application protocols. `adapters/astrbot/domain.py` exports AstrBot integration entries and intentionally requires its SDK. SDK-free event/runtime/time/action/context mappings remain available at their original individual paths. `adapters/astrbot/ports.py` declares the finite `HookHost`, `ProviderHost` and `MessageHost` views.

Hooks/attention no longer forward arbitrary unknown attributes. Their `_bindings` property exposes only the documented typed host capability view; detached test adapters can bind the same fields locally. The host remains the single owner of readiness, services, repositories and runtime-audit cleanup timestamp. Hook-local tool correlation remains separate from host resource ownership.

| Files | Responsibility and effects | Logical complexity and coupling |
|---|---|---|
| `astrbot/plugin.py` | Construct resources in dependency order and close them in lifecycle order | High: composition root; no memory algorithms |
| `astrbot/hooks.py`, `attention.py` | Map callbacks and apply the existing runtime/access/interaction decisions | Medium/high: finite typed host view, no arbitrary forwarding |
| `astrbot/registration.py` | Stable callback module/name/priority/order | Low: SDK registration only; old hooks imports remain aliases |
| `astrbot/events.py`, `runtime.py` | Event/receipt/extra correlation mapping | Medium: no SDK event imports or persistence policy |
| `astrbot/actions.py`, `model.py`, `context.py` | Host sends/provider calls and explicit context-record forwarding | Low: narrow injected host capabilities |
| `astrbot/time.py`, `topics.py` | Existing UTC+8 read/write views and Source-backed topic candidates | Medium: conversion and queue views; no new time policy |
| `persona_packs.py`, `relationship_policy.py` | Authored local files and validated relationship projections | Medium: format/access rules remain in their existing owners |

`tests/test_adapter_interface_contract.py` protects shared exports/protocols; runtime plugin tests protect finite dependencies and callback identity/order. Existing host lifecycle, cancellation, context, action and time-hook checks remain required. The UTC+8 implementation was compared as an AST with docstrings removed and is unchanged. Management routes and Node/frontend implementations are outside restructuring scope.

The host owns the observed bot identity used by background RunContext. Callback-only tool attempts belong to AstrBotHooks and are cleared after resource cleanup, so restart cannot complete an old tool receipt against a new executor. The host lifecycle regression covers identity capture, shutdown clearing and restart.

Committed-ID cache repair is shared through `app.CacheRepairs`; the composition root injects the same instance into checkpoint, extraction, context and maintenance writers. Business plans remain with each use case, and per-owner counts keep unrelated repairs out of checkpoint pending totals.
