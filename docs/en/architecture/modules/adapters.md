# adapters: AstrBot Host Integration

## Responsibility

adapters translates AstrBot events, providers, and message sending into application ports. Host objects do not leak into core, recall, or app/runtime domain policies.

## Composition root

On start, AstrBotPlugin builds Store, Cache, Tree, Graph, HybridRetriever, Source-backed Buffer, CheckpointManager, application services, AgentRuntime, Jobs, WebRoutes, and background services. On stop, it stops background and management tasks, unregisters its own routes, saves the buffer, flushes checkpoints, and finally closes Store.

main.py defines the plugin entry point and delegates lifecycle; composition and wiring live in adapters/astrbot_plugin.py. AstrBotHooks in adapters/astrbot_hooks.py maps host hooks to service calls: access decisions, input acceptance, memory injection, assistant-reply capture, post-send delivery recording, and runtime/tool observation. It does not implement extraction, capacity, or maintenance algorithms.

## Port adapters

- AstrBotRuntimeAdapter converts host messages into RuntimeInput and manages event-extra values for user/reply Source IDs, turn IDs, final recall IDs, and episode deduplication.
- AstrBotModelGateway provides ModelGateway for deferred replies.
- AstrBotActionPort provides MessageSender.
- ProviderChatModel wraps a host extraction/persona provider as ChatModel.
- SeekMemoryContextAdapter connects Runtime's MemoryContextPort to the existing RecallService.

AccessService uses full session UMO, sender ID, owner/trusted configuration, and observe_groups to decide whether a message can be observed/recalled. Host event details are normalized only at this boundary; plugin composition owns config and database path.

## Current boundaries

Hook registration must use the real plugin module path, so callbacks stay discoverable after reload. Runtime tool filtering runs before a model request; a tool observation hook after invocation is not enforcement. Host API limitations and plugin startup failures are handled at the outer boundary and must not leak AstrBot dependencies into business modules.
