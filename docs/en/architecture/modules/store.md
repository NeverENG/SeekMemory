# store: Persistence and Derived Read Models

## Responsibility

store is the only SQL boundary. [store/composition.py](../../../../store/composition.py) composes one SqliteDatabase connection with domain repositories; sharing the connection gives cross-table writes explicit transaction boundaries.

## Repository ownership

| Repository | Persisted data |
|---|---|
| ArtifactRepository | current nodes, content blobs, artifact_versions, revision-scoped artifact_evidence, edges, state_events, and commit ledger |
| SourceRepository | immutable Sources and read-only Source queries |
| ExtractionRepository | extraction_state projection, retries/backoff, deferred/extracted/dead transitions |
| LedgerRepository | append-only hash-chain entries and verification |
| RuntimeStateRepository | mutable per-session runtime state |
| RuntimeEpisodeRepository | append-only runtime outcome and content-free action metadata, with shared retention cleanup |
| DreamRepository | daily Dream status and summary |
| StoreMetricsRepository | read-only capacity counters |
| TraceStore | separate bounded JSONL Agent Run Trace, outside the Artifact version chain |

SqliteDatabase owns schema creation and migrations; repositories share its connection and do not open separate database files. Opening the database applies the schema and compatibility migrations.

## Transaction boundaries

- Artifact commit checks expected_revision and the next revision, then writes the blob, node head, version snapshot, revision-scoped evidence, state events, and ledger entry in one transaction. commit_many wraps a group of writes in one transaction; any failed write rolls back the group.
- Extraction admission writes the Source blob/row and queue state in the same transaction. Queue text is reconstructed by joining Sources; success and failure change queue state but never delete the original message.
- Source IDs use idempotent inserts, so retries do not create a second original-message row.
- Runtime action rows extend `runtime_episodes` with nullable action identity and status metadata. Existing episode rows keep their values; migration adds defaults and preserves the one-normal-episode-per-run index while allowing action rows to share a run ID. A partial unique index permits at most one terminal outcome per action, and a trigger ignores attempts arriving after that terminal. Action rows use the existing episode pruning limits.
- `runtime_state` continues storing `SessionState` as a JSON payload; the follow-up window is stored per speaker in `followup_by_speaker`, and legacy quota fields are no longer interpreted as runtime state.

## Cache

Cache holds active Artifacts only and indexes them by family, level, and subject. Recall uses it to build the candidate pool. put/remove/load increment a monotonic version; HybridRetriever uses that version to decide when to rebuild its in-memory index. Cache cannot replace a database commit and must not update before a failed CAS.

## Recovery and diagnostics

Artifact version snapshots and evidence are audit facts; the ledger hash chain checks ledger continuity. Runtime episodes, Dream state, and Run Trace have separate purposes. A diagnostic timeline is not a substitute for the Artifact change ledger. Legacy row parsing, schema evolution, and repository implementation stay inside store.

## Interface and file ownership

`store/domain.py` explicitly exports the repository bundle, repositories, cache, trace and supported ledger helpers. Existing package and implementation import paths remain compatible. `store/ports.py` declares only the cache reader and trace clock; SQLite and filesystem types remain concrete at this external edge. No store file depends on app, services or host adapters.

| File | Responsibility / resource ownership | Logical complexity and coupling |
|---|---|---|
| `composition.py` | Construct repository objects borrowing one owned SQLite connection; `close()` closes it | Low: composition, no SQL |
| `sqlite.py` | Open/close the connection, initialize the existing schema and delegate migrations; keep existing time helpers | Low/medium: SQLite and filesystem edge |
| `migrations.py` | Ordered compatible column, legacy-version, index and trigger steps | Medium: shared migration transaction, unchanged statement ordering |
| `serialization.py` | Existing JSON encoding/legacy decoding; no SQL or clocks | Low: pure conversion, stable persisted bytes |
| `artifact_codec.py` | Artifact row/header conversion; old SQL imports are compatibility aliases | Low/medium: pure conversion |
| `artifact_sql.py` | Existing Artifact SQL templates, without execution | Low: statements only |
| `artifacts.py` | Revision reads and CAS single/group commits, evidence, events, ledger and explicit graph/parent writes | High: multi-table transaction owner; no cache writes |
| `sources.py`, `extraction.py` | Immutable evidence and queue admission/outcomes; admission shares one transaction | Medium: one queue/evidence owner, no model calls |
| `ledger.py` | Single chain encoding/hash and caller-owned transaction append helper | Medium: stable byte contract, no independent commit inside helper |
| `runtime_state.py`, `runtime_episodes.py`, `dreams.py` | Distinct scheduling state, audit and daily-run transactions | Medium: no memory-policy ownership |
| `metrics.py` | Capacity measurements through the borrowed connection | Low: read-only queries |
| `cache.py`, `run_trace.py` | Derived active-memory indices and independent diagnostic JSONL | Medium: process state/file lock, separate from business truth |

Repositories borrow the connection and never close it. Public writes own their transaction; `_commit_conn`, `write_source_conn` and `append_ledger_conn` join their callers transaction and must not commit independently. `set_parent` is an existing separate compatibility column write, not an Artifact revision/edge transaction.

`tests/test_store_interface_contract.py` covers explicit identities, helper compatibility and connection sharing. Existing migration, kernel, extraction, runtime action and import-order scenarios cover behavior; these checks do not execute a live host or model.
