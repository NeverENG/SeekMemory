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

## Writes and failures

perceive/absorb.build_plan is a side-effect-free conversion: it validates evidence, subject boundary, deduplication, and family payload, then returns a write plan. IngestService is the production caller of ArtifactStore.commit. Each commit uses a CAS revision; Cache updates after the database succeeds, followed by best-effort graph linking and impression revision.

Provider/model failures do not mark pending Sources complete. ExtractionRepository owns backoff, attempt limits, and the dead state. A failure in one selected session does not automatically cancel all other selected sessions.

## Scheduling and admin work

BackgroundService starts and stops nightly/idle/Dream/weekly/checkpoint/runtime-worker cadence. WebUI Jobs serializes manual and scheduled maintenance into one active task. On plugin shutdown, background and management tasks stop before the database closes. Services do not register host events; adapters route events into them.

Entry points: [service_collection.py](../../../../services/service_collection.py), [ingest_service.py](../../../../services/ingest_service.py), [recall_service.py](../../../../services/recall_service.py), [maintenance_service.py](../../../../services/maintenance_service.py).
