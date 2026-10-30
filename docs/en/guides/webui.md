# WebUI Operations

## Open the console

Install the SeekMemory Release plugin and reload it in AstrBot. Open the management interface from the SeekMemory plugin card's plugin-view entry. Plugin configuration remains in the AstrBot configuration page. Opening a static HTML page or running pnpm dev:host does not connect to the production plugin; use dashboard Mock mode for local previews.

The AstrBot entry requires the host's authenticated administrator context; the standalone entry uses a separate administrator token. The interface can read the complete memory catalog and original evidence, so use it only in a trusted admin session.

## Local standalone console

From a source checkout with Python 3.10 or newer, build the page and start the service:

```bash
pnpm --dir dashboard install --frozen-lockfile
pnpm --dir dashboard build
export SEEKMEMORY_CONSOLE_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
python3 scripts/console_http.py --data-dir ./data/console --port 8766
```

Open `http://127.0.0.1:8766`, keep the default API address, and connect using the administrator token in the environment variable. Tokens require at least 32 non-whitespace ASCII characters and live only in page memory. Refreshing, disconnecting, or replacing the service token requires entering it again. The service binds only to `127.0.0.1` and provides no remote deployment entry.

The data directory contains the existing `memory.db`, `persona_packs/`, and `run_traces.jsonl` formats. Start with a new directory. To inspect existing data, stop its host and back it up before copying the complete directory offline. Do not let AstrBot or another standalone process manage the same directory concurrently: each process owns an active cache that cannot track another process's edits. Existing AstrBot configuration and database formats are unchanged.

The standalone console supports the memory list, details, manual revisions, persona packs, and recall diagnostics. It starts no chat host, model, extraction queue, or maintenance scheduler; maintenance buttons are unavailable. Lifecycle logs are empty. Run traces load an allowlisted offline snapshot from the selected directory read-only at startup. The trace API filters its in-memory view to seven days and at most 5,000 events by default. Starting, reading, and closing never rewrite the original file; the producer owns persisted retention. Restart after replacing an offline snapshot. Import-task status still awaits a real memory-import API; persona-pack import does not provide that task status.

For development, run `pnpm --dir dashboard dev:standalone` and add `--allow-origin http://127.0.0.1:5176` to the service command. Enter `http://127.0.0.1:8766/api/` on the connection page. Allowed origins must be explicit local HTTP origins; other page origins are rejected by default. Stop with Ctrl+C. Restart reads the token from the environment and creates no token file.

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

On the run trace page, query by full run ID, run result, and last-update time range. Times use the device timezone and include both boundaries. Combine or clear the conditions. The server returns every available step of matching runs inside its retention window; recall flags can further filter current results. Failure steps come directly from error events. “Previous run unfinished” means no end was recorded and does not identify a cause. The page marks timelines whose steps were not fully retained.

Both entries use the same `GET manage/traces` query contract. For example, `?status=error&since=2026-10-29T00:00:00Z` selects failed runs last updated at or after that instant; add `run_id=<32-character-run-id>` for an exact match. Neither the interface nor the page needs internal business tables. See [runtime design](../architecture/modules/runtime.md#run-trace-event-boundary) for the allowlist and retention limits.

See [development setup](development.md) for the dashboard mock and build workflow.

## Persona console and memory map

The sidebar groups home, persona studio, memories, impressions, persona packs and Dream. Run traces have a single entry under System.
The studio compares historical revisions and requires a reason and confirmation before rollback. The store separates bundled seeds from local blueprints; installing creates a new active-persona revision without creating Sources or calling a model. Exporting the current persona retains only blueprint allowlisted fields, excluding raw dialogue, source evidence, ledger and revision history. Import and update only save files; installation requires a separate confirmation.

The memory map uses Canvas perspective projection. It filters first, then displays the 80 most recently updated memories, with 40/80/120 choices. The surface mesh is decorative geometry, not semantic evidence; dashed links on selection represent associations supplied by the API. Drag to rotate, zoom, hover to preview and select to expand. Motion respects reduced-motion preferences. Protected nodes stay masked until an explicit protected-detail action.

Lifecycle logs refresh every three seconds and support pause, follow-latest and expandable details. Attention log states allow-reply and skip-reply indicate whether policy allowed or blocked this turn, not whether a message was delivered. Both states are available under More filters.
