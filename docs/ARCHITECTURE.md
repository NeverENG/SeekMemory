# SeekMemory Architecture v4

## Core rule

Source is the only immutable truth. Artifact is a derived, versioned interpretation.

## Layers

```text
AstrBot events / cron / external input
        |
        v
main.py: composition and adapters only
        |
        v
app/: use cases, DTOs, ports
        |
        v
core/: Source, Artifact, Strength, versioning, disclosure
        ^
        |
store/ perceive/: SQLite, cache, LLM adapter
```

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
5. LLM calls never run inside a DB transaction.

## Read and disclosure

Recall reads from in-memory indexes. Disclosure is one universal score:

exposure = audience_overlap * subject_fit * topic_fit * (1 - sensitivity)

Levels: full >= 0.55, paraphrase >= 0.18, hint >= 0.03, otherwise silence.
Paraphrase uses a generic safe sentence, never raw content or extractor tags. Cross-session text is never injected as a direct quote.

## I/O targets

- Recall: zero SQL reads after warmup; use cache indexes by family, level and subject.
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

All production writes now use `DB.commit()` with expected revision, version snapshots, evidence
links and ledger entries. `DB.upsert()` remains only as a legacy compatibility primitive.

## Topic, subject and time

Buffer entries are typed `DialogueTurn` objects. Topics split on a 90-minute gap or low
character-bigram similarity; `topic_ttl_seconds` forces aged topics to extraction.
The extractor returns `subject_kind`, `subject_id`, `event_at` and validity dates.
`TimeSpan.created` uses event time, not extraction time.

## Current implementation status (v0.3.1)

- Source is persisted for both user and assistant messages, including group sessions.
- Production writes use CAS DB.commit with versions, evidence and ledger.
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
- Extraction batches rotate one topic per session. The scheduler keeps its own
  bounded `webui/trace.py` ring for capacity samples, separate from the
  business Journal event log.
- Not implemented yet: local vector retrieval, reflection wiring, RBAC and persona source policy.
