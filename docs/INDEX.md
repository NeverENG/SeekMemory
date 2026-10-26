# Code Index

> Start here: [docs/README.md](README.md), then read the [repository development skill](../.agents/skills/seekmemory-dev/SKILL.md) and the relevant technical contracts.

## Directory map

| Directory | Responsibility | Start here |
|---|---|---|
| core/ | Artifact and Source values, Strength, versioning, disclosure, retrieval values | core/README.md |
| app/ | Use-case DTOs, ports, flush policy, checkpoint policy | docs/ARCHITECTURE.md |
| store/ | SQLite repository, cache/read model, ledger | store/README.md |
| perceive/ | Extraction prompt, ChatModel adapter, topic buffer | perceive/README.md |
| recall/ | Candidate retrieval, scoring, disclosure-aware assembly | recall/README.md |
| maintain/ | Decay, merge, persona and reflection policies | maintain/README.md |
| webui/ | Host routes, management service, task mutex, lifecycle journal | docs/CONTRACT.md |
| dashboard/ | WebUI source, standalone mock and strict frontend checks | dashboard/README.md |
| docs/webui/ | Plugin WebUI guide and screenshots | docs/webui/README.md |
| scripts/package_plugin.py | Runtime whitelist and Release ZIP packaging | CONTRIBUTING.md |
| tests/ | Unit, contract, integration, host and smoke tests; layer map in tests/layers.py | docs/TESTING.md |
| docs/ | Architecture, contracts, operator guides and durable design decisions | docs/README.md |
| docs/INTERFACES.md | Public protocols, DTOs and contract tests | docs/INTERFACES.md |
| docs/README.md | Documentation entry point and status legend | docs/README.md |
| .agents/skills/seekmemory-dev/SKILL.md | Normative development workflow; detailed topics live in its reference/ directory | ../.agents/skills/seekmemory-dev/SKILL.md |
| docs/INVARIANTS.md | Non-negotiable identity, privacy, recovery and reinforcement rules | docs/INVARIANTS.md |
| docs/TESTING.md | Test layers, commands and known coverage gaps | docs/TESTING.md |
| docs/PERSONA_SEED.md | Persona file schema and one-time bootstrap contract | docs/PERSONA_SEED.md |
| docs/DEV-SETUP.md | Backend tests and dashboard local development | docs/DEV-SETUP.md |
| scripts/run_tests.py | Run one test layer locally or in CI | docs/TESTING.md |
| main.py | Entry point composition only | main.py |
| adapters/astrbot_plugin.py | AstrBot wiring and lifecycle | adapters/astrbot_plugin.py |
| adapters/astrbot_hooks.py | AstrBot event mapping and handler registration | adapters/astrbot_hooks.py |
| app/runtime/tracing.py + store/run_trace.py | Content-free run correlation and bounded JSONL traces | [Run Trace contract](CONTRACT.md#agent-run-traces) |

## Dependency direction

```text
main.py entrypoint
        |
        v
adapters/astrbot_plugin.py + adapters/astrbot_hooks.py
        |
        v
services/ application services
        |
        v
app/ DTOs, contracts, runtime and pure policy
        |
        v
core/ Artifact kernel
        ^
        |
store/ perceive/ recall/ maintain/ adapters
```

Rules:

- core/ imports no storage, SDK, plugin or app code.
- app/ imports core/ only; external systems stay behind ports.
- services/ composes app/, core/, recall/, perceive/ and maintain/; it imports no AstrBot or adapter code.
- main.py contains no function bodies; host handlers live in adapters/astrbot_hooks.py and wiring lives in adapters/astrbot_plugin.py.
- adapters/astrbot_hooks.py contains no extraction, capacity or maintenance algorithm.
- store/ is the only place that writes SQL.
- webui/routes.py adapts the host. services/management_service.py calls core/store/recall.
- webui/jobs.py and webui/journal.py stay independent of the host.
- Business modules do not import main.py at runtime. WebUI routes may use type-only references.
- recall/ and maintain/ are migration zones; do not add new cross-layer dependencies.

## Write path

```text
AstrBot user message
  -> main.buffer_message
  -> Source(user) + DialogueTurn buffer with topic_id
  -> backlog / idle / nightly extraction
  -> ChatModel
  -> Artifact construction + validation
  -> artifacts.commit(expected_revision)
       -> blob
       -> node head
       -> artifact_versions
       -> artifact_evidence
       -> ledger
  -> cache.put

assistant reply
  -> main.capture_reply
  -> Source(assistant, reply_to=user source)
  -> Buffer.add(role=assistant) + extraction_state
```

## Read path

```text
AstrBot on_llm_request
  -> recall.pipeline.build_block
  -> visible scope filter
  -> GraphRetriever (activation), or optional HybridRetriever (+ BM25 lexical)
  -> select / evidence gate
  -> disclosure (full / paraphrase / hint / silence)
  -> assemble safe text
  -> system prompt
```

Recall does not write. Reinforcement is queued and flushed by app/checkpoint.py.

BM25 默认开启（`bm25_enabled=true`），配置权重默认为 1.0。插件入口与管理诊断共用
长生命周期 HybridRetriever；Cache.version 变化后重建索引，查询统计只使用可见候选池。
`recall/tokenizer.py` 提供无依赖字符 bigram；`recall/bm25.py` 提供正文/标签倒排表。
校准与独立验收入口为 `benchmarks/bm25.py`；配置边界见 [CONTRACT.md](CONTRACT.md)，验收口径见 [benchmarks/README.md](../benchmarks/README.md)。

## WebUI path

```text
AstrBot plugin page
  -> webui/routes.py
  -> services/management_service.py
  -> store/__init__.py repositories + cache + recall pipeline
  -> JSON response or SSE lifecycle event
```

Management writes reuse Artifact commit with expected revision. Recall diagnostics do not consume
one-time delivery state.

## Project tracking

Track planned work and review history in [GitHub Issues](https://github.com/NeverENG/SeekMemory/issues) and [Pull Requests](https://github.com/NeverENG/SeekMemory/pulls). Keep enduring design decisions and technical contracts in repository docs; do not copy per-issue or per-PR work logs here.

## Hard rules

1. Only core/artifact.py defines Artifact data structures.
2. Only store/ writes SQL; store/__init__.py composes repositories.
3. All production writes use artifacts.commit with expected revision.
4. Source is immutable truth; Artifact is derived interpretation.
5. Cross-session content must pass disclosure before injection.
6. Track P0/P1 work in GitHub Issues and PRs; update durable technical docs when behavior or contracts change.
