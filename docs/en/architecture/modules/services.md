# services: Use-Case Orchestration

## Responsibility

services combines domain objects, app ports, and perceive, recall, and maintain into complete use cases. The layer has no general-purpose dependency-injection container and does not own SQL; ServiceCollection is a typed bundle of services.

## Capability boundaries

| Service | Owned work |
|---|---|
| AccessService | Decides whether a session may be remembered, observed, or recalled under owner/trusted/group configuration |
| RecallService | Applies budget and degradation inputs, calls the single recall pipeline, and offers a preview that does not write delivery state |
| IngestService | Selects pending topics, resolves providers, calls the model, builds Artifacts, and owns production writes, retries, and usage totals |
| CapacityService | Reads a capacity snapshot, evaluates CapacityGovernor, and applies backpressure, deferred release, batch/recall reduction, or maintenance actions |
| MaintenanceService | Runs self-impression aggregation, decay, merge, and persona consolidation/synthesis in order |
| ManagementService | Queries catalog, detail, versions, and evidence; validates admin edits and rollback; reuses RecallService for diagnostics |
| StatusService | Supplies persona timeline and ledger-chain health to management UI |
| BackgroundService | Owns periodic, idle, and Dream cadence; delegates work to the services above |
| TreeService | Reads children and impressions; coordinates memory revisions, cache updates, and parent/child storage |

## Writes and failures

perceive/absorb.build_plan is a side-effect-free conversion: it validates evidence, subject boundary, deduplication, and family payload, then returns a write plan. IngestService is the production caller of ArtifactStore.commit. Each commit uses a CAS revision; Cache updates after the database succeeds, followed by best-effort graph linking and impression revision.

Provider/model failures do not mark pending Sources complete. ExtractionRepository owns backoff, attempt limits, and the dead state. A failure in one selected session does not automatically cancel all other selected sessions.

TreeService is implemented entirely in `services/tree_service.py`. It uses `TreeArtifactStore` and optional `TreeCache` from `app/ports.py`, without importing storage implementations. Child reads prefer cache and fall back to storage without filling cache; impression reads fall back only when the cached level is empty.

`add_under` rejects self-parenting, then commits the memory, updates cache, sets the parent column, and adds the tree edge in order. These steps are not one transaction; failures propagate, and a failed commit leaves cache unchanged. An existing memory may gain a new revision, but the return value remains the original input. Setting or clearing the parent column does not delete old edges. The host currently constructs the service; its writes are covered by smoke and contract checks rather than the production ingestion path.

## Scheduling and admin work

BackgroundService starts and stops nightly/idle/Dream/weekly/checkpoint/runtime-worker cadence. WebUI Jobs serializes manual and scheduled maintenance into one active task. On plugin shutdown, background and management tasks stop before the database closes. Services do not register host events; adapters route events into them.

Entry points: [service_collection.py](../../../../services/service_collection.py), [ingest_service.py](../../../../services/ingest_service.py), [recall_service.py](../../../../services/recall_service.py), [maintenance_service.py](../../../../services/maintenance_service.py).

## Interface and file ownership

`services/domain.py` explicitly re-exports the supported services. `services/ports.py` declares required buffer, provider, journal, logger, job and trace capabilities and reuses the existing app repository/cache protocols. These entry files contain no business implementation. Existing package and implementation imports keep the same objects. Composition owns construction and shutdown of every injected resource.

| Implementation | Responsibility and effects | Logical complexity / coupling |
|---|---|---|
| `ingest_service.py` | Resolve providers, invoke models and coordinate ordered extraction writes | High: owns the model → plan → commit → follow-up sequence; these stages share one receipt rather than independent state |
| `ingest_selection.py` | Group resolved topics and check usage budgets | Low: pure rules, no provider or repository calls |
| `ingest_state.py` | Prepared plans and per-memory stage progress | Low: process-local data; no resource ownership |
| `diagnostics.py` | Contain ordinary diagnostic failures while preserving business exceptions/cancellation | Low: diagnostic calls and spans only |
| `maintenance_service.py` | Evidence reads, model calls and ordered maintenance | High: coordinates several writers; no SQL |
| `persona_policy.py` | Evidence selection, configured weight normalization and revision construction | Low/medium: pure rules over supplied data |
| `management_service.py` | Compatible management entrypoints | Low: delegates explicit reads and commands |
| `management_queries.py` | Catalog, detail, packs and version projections | Medium: repository reads; no memory writes |
| `management_commands.py` | Validate confirmed edits, seed installation, rollback and pack actions | Medium: commit first, then cache; no resource ownership |
| `background_service.py` | Task lifecycle and cadence | Medium: owns its tasks; delegates business work |
| `access_service.py`, `recall_service.py`, `capacity_service.py`, `status_service.py`, `tree_service.py` | Existing access, recall, pressure, status and tree use cases | Separate owners; tree follow-up writes are not one transaction |

Interface identities and fresh top-level/plugin-namespace import orders are covered by `tests/test_services_interface_contract.py`. Existing extraction, persona, management HTTP and architecture scenarios exercise the delegated behavior. They do not establish real-model or real-host coverage.

## Extraction recovery

`IngestService` serializes model/plan creation and owns prepared plans in `ingest_state.py`. Each memory has separate durable-commit, cache and best-effort enrichment progress. The service records a successful commit before any fallible diagnostics or cache work. A failed commit retains that exact prepared memory; a cache retry reads the latest database head. Neither path replays the model or creates an already committed memory again. `extract()` reports newly committed memories per invocation; retries do not add usage for an earlier call.

Scheduled flushes explicitly request queue confirmation. Failed confirmation retains the receipt and only that confirmation is retried; fresh Source rows remain pending. A valid empty model result can also retain a queue-only receipt. Provider, parse and evidence failures retain the original bounded model retry path. Optional graph or impression failures are reported without negating persistence.

`IngestService.retry_writebacks()` performs prepared persistence without model calls and returns completed operations. `BackgroundService.retry_writebacks()` delegates extraction/runtime compensation before idle or scheduled extraction gates, at checkpoints, and once after its tasks stop. Recovery is process-local; no new database/schema or crash/multiprocess exactly-once guarantee is introduced.

A failed flush with completed commits raises the `RuntimeError`-compatible `app.contracts.ExtractionFailure` with completed memory/topic counts and a content-free error type. Dream includes these counts in its failure result and journal; completed writes are not reported as zero. Successful return shapes remain unchanged. Regression scenarios live in `tests/test_ingest_failure_recovery.py`. Reverting the recovery commit restores the previous execution path without a data migration.

Transparent diagnostic wrappers mark their frames with `__tracebackhide__`; Journal skips those frames when recording the business source location. File/line/function ownership and payload privacy remain tested independently of private function names.

Flush failures with no completed commit preserve the original exception type; completed-write failures carry explicit progress instead.

Memory context construction uses the pure `RecallService.query()`. Explicit inclusion recording is forwarded through the optional generic `MemoryContextRecorder`; ordinary host hooks call it after request attachment, background dispatch immediately before model invocation. The runtime contains no designated rules. Existing `RecallService.build()` remains a compatibility query-plus-recording entry.

Background compensation also delegates the context-inclusion writer, so pending designated commits/cache repairs can finish while extraction/speaking are disabled and before database shutdown.

MaintenanceService retains its maintenance writer for exact prepared commits and latest-head cache repairs. Background compensation delegates it even with extraction/speaking disabled and before database shutdown. Pending repairs block derivation of further maintenance plans from a stale view.

Committed-ID cache repair is shared through `app.CacheRepairs`; the composition root injects the same instance into checkpoint, extraction, context and maintenance writers. Business plans remain with each use case, and per-owner counts keep unrelated repairs out of checkpoint pending totals.
