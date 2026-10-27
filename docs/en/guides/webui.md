# WebUI Operations

## Open the console

Install the SeekMemory Release plugin and reload it in AstrBot. Open the management interface from the SeekMemory plugin card's plugin-view entry. Plugin configuration remains in the AstrBot configuration page. Opening a static HTML page or running pnpm dev:host does not connect to the production plugin; use dashboard Mock mode for local previews.

All management API calls require the host's authenticated administrator context. The interface can read the complete memory catalog and original evidence, so use it only in a trusted admin session.

## Memory library

- Filter records by category, state, scope, keyword, and source session. Details can show the Artifact, versions, version-scoped evidence, Sources, and ledger entries.
- When editing payload, scope, or state, enter a reason and confirm. The server validates the family and checks expectedRevision. If another task changed the record, refresh its detail before deciding whether to retry.
- Forgotten items can be restored to active by creating a revision. Merged records cannot be restored independently or edited into a fabricated merge relation.
- The persona timeline shows historical revisions and supports rollback. Rollback creates a new revision on the same Persona ID; history is not deleted.

## Recall diagnostics

Enter the query, full session UMO, and actual speaker ID to preview the assembled block, candidates, and disclosure decisions. Diagnostics use the real recall path but do not call a model, write memory, or consume designated one-time delivery state. They preview memory context, not the full model answer; random exploration may change candidates between runs.

## Status and maintenance tasks

- The status page shows engine state, ledger verification, provider configuration, pending sessions/topics, capacity, Dream, and checkpoint data. The provider check sends no model request and does not guarantee network access, quota, or a successful generation.
- **Extract now** processes queued topics and may call the configured extraction model. Check written, skipped, warning, and remaining pending counts, not only task completion.
- **Weekly maintenance** runs self-impression aggregation, decay, merging, and persona handling. A bootstrapped persona may receive one bounded synthesis call when its interval is due; failures keep the current persona.
- Only one maintenance job runs at a time. Cancelling stops remaining work; completed commits are not rolled back.

## Logs and run traces

The lifecycle log helps locate business stages, durations, source locations, and error types. It is a bounded diagnostic record, not a permanent audit archive. Agent Run Trace shows correlated request, recall, tool, and send events without message text or model responses. “Memory injected” means content entered the request context; it does not prove the model used it.

Capacity Trace is a separate runtime sample. These streams have different purposes and are not interchangeable as business facts.

See [development setup](development.md) for the dashboard mock and build workflow.
