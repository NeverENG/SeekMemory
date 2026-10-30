# Architecture Overview

## What the system models

SeekMemory stores original conversation and conclusions about it separately:

- A **Source** is an immutable original message with its ID, session, speaker, role, time, reply relation, and text.
- An **Artifact** is a revisable conclusion derived from sources. Its payload is validated by family, and its lineage points to evidence Sources and upstream Artifacts.
- An Artifact keeps its ID as revisions increase. The database stores the current head, version snapshots, version-scoped evidence, and ledger entries.

These fields are not interchangeable: subject_id identifies who a conclusion is about; said_by identifies who produced the current conclusion; lineage.sources identifies the original supporting messages. A Source session_id identifies the conversation where evidence originated.

## Runtime layers

| Module | Provided capabilities | Required capabilities and resource ownership |
|---|---|---|
| adapters | Host events, sending, models and time conversion | Construct services/Store and close owned resources; host SDK stays at the edge |
| services | Access, ingestion, recall, maintenance, management and background use cases | Borrow app ports and combine business modules without SQL; each use case owns its unfinished plan |
| app | Shared data, protocols, nightly/runtime orchestration | Borrow injected capabilities; one shared owner repairs committed-ID cache work |
| core | Source, Artifact, versions and pure policy | No app/database/SDK imports; Graph borrows a store port, with existing clock/threshold reads preserved |
| perceive | Message views, response parsing and extraction plans | Borrow Source/queue ports; legacy file adapters own paths, plans do not commit memory |
| recall | Query, disclosure, assembly and explicit context recording | Queries do not write memory; recording owns pending progress, legacy build retains compatible side effects |
| maintain | Evidence analysis, revision plans and maintenance writes | Separate pure rules from I/O; resume prepared plans without recreating committed interpretations |
| store | SQLite repositories, cache and persistence | Store owns one connection and repositories borrow it; SQL/transactions remain here |

Business modules still expose domain.py and ports.py; core groups domain implementations and exports in core/domain/ and required protocols in core/port/. Legacy module import paths remain compatibility entries. Python management services are included; webui/dashboard/DSH structure retains its existing owners.

The dependency direction is enforced by code boundaries: core does not depend on the host or storage; SQL belongs in store; AstrBot types stay in adapters and the host route layer; services compose business modules without issuing SQL.

## Write path

1. AstrBot hooks pass messages and session identity through AccessService and AgentRuntime. Observable user messages are recorded by RunRecorder as immutable Sources and admitted to the Source-backed extraction queue. Assistant replies are also captured as Sources in the model-response hook, with the actual reply_to relation.
2. Buffer builds a DialogueTurn view over pending Sources and groups them by session and topic. If a reply references an already processed user message, its parent Source may be read back as pairing context without being queued again.
3. IngestService selects topics and a provider; Dream may first run deterministic importance triage. perceive converts model output into a side-effect-free ExtractionPlan: parse JSON, validate evidence, deduplicate within subject/scope, and construct and validate Artifacts.
4. IngestService commits each production Artifact with expected_revision. The Artifact head, version snapshot, version-scoped evidence, state events, and ledger entry are written in one SQLite transaction. Cache is updated only after the commit; relation edges are best-effort afterward.
5. Extraction failures retain queue rows and record bounded error types, retry times, and attempt counts. Sources are not deleted on success or failure.

## Recall path

1. The host request hook checks AccessService. A runtime context adapter calls RecallService, which delegates to the single recall pipeline.
2. The pipeline reads active Artifacts from Cache. It excludes family=secret and designated records outside their owning conversation. Ordinary memory with private, shared, or shadow scope can enter the candidate pool; scope is not a hard session visibility gate for ordinary memory.
3. Pure time questions and non-memory intents do not start normal retrieval. Other queries are ranked by GraphRetriever or HybridRetriever, then pass an evidence gate and a bounded assembly budget. HybridRetriever combines graph activation with local BM25 lexical signals and makes no model or network call.
4. When recall is sparse and the query has memory intent, a bounded recent Source query may run. Source IDs are used to find active Artifacts with evidence on their current revision. Source text is never copied into the prompt, diagnostic summary, log, or assembled block.
5. Candidates pass a shared disclosure decision before assembly. Disclosure combines session context, subject fit, scope, sensitivity, and query relevance; it yields full text, a fixed paraphrase, a fixed hint, or silence. Designated delivery separately requires a private chat, a trigger match, and an unused delivery state.
6. The assembler orders persona, impressions, scenes/details/facts, and other content within a character budget. It returns the Artifact IDs that actually reached the final block. Designated recording happens explicitly when its body enters model context; ordinary host response callbacks queue reinforcement from actually referenced IDs. Querying alone performs neither write.

## Data and side-effect boundaries

- One Store owns one SQLite connection. Repositories share it so Artifact commits and Source admission have explicit transaction boundaries.
- Cache is a derived read model of active Artifacts. Cache.version tells derived indexes such as BM25 when to rebuild; it is not the database of record.
- runtime_state is mutable scheduling state; runtime_episodes is append-only runtime audit metadata. Neither is a Source or Artifact.
- The lifecycle Journal, capacity Trace, and Agent Run Trace serve different diagnostic needs. Run Trace is bounded and field-whitelisted; it is not the business ledger.
- Memory and diagnostic persistence failures should not block ordinary chat. Incomplete input must not be silently marked as successfully extracted.
- Relationship state is a versioned derived Artifact consolidated by Maintenance from exact Source-backed categorical observations. It never changes Source capture, Recall, disclosure, or authorization. The AstrBot adapter applies its content-free interaction gate after the existing Runtime decision; app/runtime remains relationship-free.

## Current implementation boundaries

This overview describes current code, not unimplemented proposals. Retrieval uses graph activation and optional BM25; there is no local vector search. maintain/reflect.py provides pure rule signals but has no production caller. The Agent Runtime gate is disabled by default; when enabled, the deferred ambient reply path does not run the full AstrBot tool loop. See the [module design pages](modules/core.md).

## Why coherent long files remain

| File | Coherent responsibility and verification |
|---|---|
| `services/ingest_service.py` | One use case owns model calls, exact plans and stage recovery; pure batching/budget and state are separate. Ingestion/recovery integration scenarios protect ordering. |
| `adapters/astrbot/plugin.py`, `hooks.py` | Resource composition/lifecycle and finite host callbacks; registration and mapping are separate. Independent host lifecycle/hook contracts protect them. |
| `app/runtime/recorder.py`, `dispatch.py` | Source/projection/reinforcement/audit stages and two background delivery paths; retain one progress owner and path-specific retries. Runtime writeback/recovery scenarios protect them. |
| `store/artifacts.py`, `perceive/buffer.py` | One transaction aggregate and one pending-view owner; serialization/SQL/files/rules are separate while complete commit/publication ordering remains local. Storage/queue failure tests protect it. |

Do not split these into forwarding layers merely to reduce line counts. Interfaces, rules, state and effects have explicit owners; split further only when another independently describable responsibility appears.
