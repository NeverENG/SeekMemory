# Code Index

> Start here. Then read docs/ARCHITECTURE.md, docs/CONTRACT.md, CONTRIBUTING.md and AGENTS.md.

## Current version

```text
v0.3.1 + WebUI branch
```

## Directory map

| Directory | Responsibility | Start here |
|---|---|---|
| core/ | Artifact and Source values, Strength, versioning, disclosure, retrieval values | core/README.md |
| app/ | Use-case DTOs, ports, flush policy, checkpoint orchestration | docs/ARCHITECTURE.md |
| store/ | SQLite repository, cache/read model, ledger | store/README.md |
| perceive/ | Extraction prompt, ChatModel adapter, topic buffer | perceive/README.md |
| recall/ | Candidate retrieval, scoring, disclosure-aware assembly | recall/README.md |
| maintain/ | Decay, merge, persona and reflection policies | maintain/README.md |
| webui/ | Host routes, management service, task mutex, lifecycle journal | docs/CONTRACT.md |
| dashboard/ | WebUI source, standalone mock and strict frontend checks | dashboard/README.md |
| docs/webui/ | Plugin WebUI guide and screenshots | docs/webui/README.md |
| scripts/package_plugin.py | Runtime whitelist and Release ZIP packaging | CONTRIBUTING.md |
| tests/ | Unit, integration, kernel and WebUI tests | tests/test_kernel.py |
| docs/ | Architecture, contracts and issues | docs/issues/INDEX.md |
| main.py | AstrBot event mapping and composition only | main.py |

## Dependency direction

```text
main.py / AstrBot adapter
        |
        v
app/ use cases and ports
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
- store/ is the only place that writes SQL.
- webui/routes.py adapts the host. webui/service.py calls core/store/recall.
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
  -> DB.commit(expected_revision)
       -> blob
       -> node head
       -> artifact_versions
       -> artifact_evidence
       -> ledger
  -> cache.put

assistant reply
  -> main.capture_reply
  -> Source(assistant, reply_to=user source)
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
校准与独立验收入口为 `benchmarks/bm25.py`，限制和回滚方式见 [ISSUE-0024](issues/ISSUE-0024.md)。

## WebUI path

```text
AstrBot plugin page
  -> webui/routes.py
  -> webui/service.py
  -> store/db.py + cache + recall pipeline
  -> JSON response or SSE lifecycle event
```

Management writes reuse Artifact commit with expected revision. Recall diagnostics do not consume
one-time delivery state.

## Active design work

- BM25 hybrid retrieval（默认开启）：[实现与验收](issues/ISSUE-0024.md)。
- 本地向量的后续约束同样记录在 ISSUE-0024：用户预装模型、运行时离线，本次不实现。
- WebUI follow-up: server-side pagination, editable source view, and release download_url.
- Future: reflection wiring, RBAC, capacity governance, persona source policy.

## Hard rules

1. Only core/artifact.py defines Artifact data structures.
2. Only store/db.py writes SQL.
3. All production writes use DB.commit with expected revision.
4. Source is immutable truth; Artifact is derived interpretation.
5. Cross-session content must pass disclosure before injection.
6. New P0/P1 work needs an issue and a PR record.
