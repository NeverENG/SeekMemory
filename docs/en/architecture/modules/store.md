# store: Persistence and Derived Read Models

## Responsibility

store is the only SQL boundary. [store/__init__.py](../../../../store/__init__.py) composes one SqliteDatabase connection with domain repositories; sharing the connection gives cross-table writes explicit transaction boundaries.

## Repository ownership

| Repository | Persisted data |
|---|---|
| ArtifactRepository | current nodes, content blobs, artifact_versions, revision-scoped artifact_evidence, edges, state_events, and commit ledger |
| SourceRepository | immutable Sources and read-only Source queries |
| ExtractionRepository | extraction_state projection, retries/backoff, deferred/extracted/dead transitions |
| LedgerRepository | append-only hash-chain entries and verification |
| RuntimeStateRepository | mutable per-session runtime state |
| RuntimeEpisodeRepository | append-only runtime outcome metadata and retention cleanup |
| DreamRepository | daily Dream status and summary |
| StoreMetricsRepository | read-only capacity counters |
| TraceStore | separate bounded JSONL Agent Run Trace, outside the Artifact version chain |

SqliteDatabase owns schema creation and migrations; repositories share its connection and do not open separate database files. Opening the database applies the schema and compatibility migrations.

## Transaction boundaries

- Artifact commit checks expected_revision and the next revision, then writes the blob, node head, version snapshot, revision-scoped evidence, state events, and ledger entry in one transaction. commit_many wraps a group of writes in one transaction; any failed write rolls back the group.
- Extraction admission writes the Source blob/row and queue state in the same transaction. Queue text is reconstructed by joining Sources; success and failure change queue state but never delete the original message.
- Source IDs use idempotent inserts, so retries do not create a second original-message row.

## Cache

Cache holds active Artifacts only and indexes them by family, level, and subject. Recall uses it to build the candidate pool. put/remove/load increment a monotonic version; HybridRetriever uses that version to decide when to rebuild its in-memory index. Cache cannot replace a database commit and must not update before a failed CAS.

## Recovery and diagnostics

Artifact version snapshots and evidence are audit facts; the ledger hash chain checks ledger continuity. Runtime episodes, Dream state, and Run Trace have separate purposes. A diagnostic timeline is not a substitute for the Artifact change ledger. Legacy row parsing, schema evolution, and repository implementation stay inside store.
