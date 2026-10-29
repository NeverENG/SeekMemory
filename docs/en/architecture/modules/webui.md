# WebUI: Management API and Dashboard

## Layers

- `webui/` keeps host-neutral jobs, journal, and trace primitives; AstrBot management routes live in `adapters/astrbot/web.py`, where the adapter owns authentication, method/body limits, and status mapping.
- services/management_service.py implements framework-independent catalog, detail, edit, persona bootstrap/rollback, and recall-diagnostic use cases.
- dashboard/ is the React/TypeScript management interface, organized around memory library, control/diagnostics/logs/run traces/persona evidence workspaces.
- The AstrBot page bridge sends authenticated host requests to the plugin API; a static page and development mock do not connect to the real database.

## Management writes

Management detail may display Artifact text, version snapshots, version-scoped evidence, Sources, and ledger data. An edit must include the read-time expectedRevision, confirmation, supported payload/scope/state, and a reason. The backend validates the family and commits through ArtifactStore; a revision race returns a conflict. The WebUI never writes SQL or Cache directly.

Persona rollback loads historical content and creates a new revision on the same stable ID; it never deletes history. A merged ordinary Artifact cannot be restored independently. While a maintenance task is running, edit and rollback are rejected to avoid concurrent changes.

## Diagnostics and observability

Recall diagnostics reuse RecallService with dry_run, skipping designated given-state writes. They do not call a model or alter memory. The status provider check verifies configuration only and does not send a model request.

Jobs limit manual and scheduled maintenance to one active task. Journal stores bounded business-stage events and error types/source locations. Agent Run Trace is stored separately by TraceStore with an allowlist; capacity Trace is another in-memory ring. These streams have distinct purposes and must not store message text, model responses, or tool arguments/results.

The root openapi.yaml is the management API source of truth. dashboard/src/contracts/generated.ts is maintained by code generation, while Zod continues to validate runtime inputs. See the [WebUI operations guide](../../guides/webui.md) and [dashboard development setup](../../guides/development.md).

## Persona console read models (GitHub #82 / #83)

All routes below use the existing authenticated `WebRoutes` boundary. OpenAPI is
canonical; the production page adapter validates responses with Zod.

| Action | Bounded output / command |
|---|---|
| `GET manage/graph` | Latest 120 artifacts, at most 240 real/derived associations; no Source body; secret/designated/shadow labels masked |
| `GET manage/impressions?offset=0` | 100 latest impression cards grouped by subject **and scope**; identities are not merged across privacy boundaries |
| `GET manage/dream` | Latest 100 runs, whitelisted metrics only; absent triage metrics remain null, never fabricated as zero |
| `GET manage/packs?collection=official&offset=0` | 24 canonical persona-file summaries; `mine` reads only the plugin data directory |
| `GET manage/pack?reference=official/big_fish` | Validated canonical persona file, up to 64 KiB |
| `POST manage/persona` | Explicitly confirmed `install`, `import` or recoverable `remove`; all reject while maintenance is active |

Pack detail includes a SHA-256 `digest` of the normalized seed. Install requires
`expectedId`, `expectedRevision` and `expectedDigest`; changed preview content
returns 409 before any write. The already-verified seed delegates to the existing
bootstrap path. Import saves a blueprint only. Replacing an existing local pack
requires its `expectedVersion` and a different new version; a backup is retained.
The local pack file adapter publishes complete files atomically and never writes
Artifacts, Sources, ledger rows or model requests. Official packs are immutable.

The home event feed reuses `manage/traces`; it does not create a second speech or
message-body endpoint. Existing detail/update/diagnose/task contracts remain intact.


The persona console also consumes `POST manage/rollbackPersona` with
`{id, revision, reason, confirmed}`. It compares current and selected text before
confirmation and refreshes status after success. The existing management service
creates a new revision and records the reason in the ledger; history is preserved.
The route is now declared in OpenAPI and validated by the production client.
Dream renders `budget.stopped` and `dream_enabled` explicitly, rather than treating
a budget-limited run as full completion or disabled scheduling as active.


`GET manage/packArtwork?reference=…` returns bounded PNG base64 through administrator authentication. `GET manage/packExport?reference=…` exports a complete pack without exposing the data directory. Catalogue responses carry only an optional content-free artworkRef, not image bytes. `POST manage/persona` adds importPack, preserving confirmation, maintenance exclusion and expectedVersion checks. Its request limit is 3 MiB; other management writes remain limited to 64 KiB. Preview digests cover seed, license and artwork; installation passes only the canonical seed to bootstrap. See the [persona seed guide](../../guides/persona-seed.md) for the envelope format.

## Graph snapshot and interaction

`manage/graph` reads a fixed snapshot of at most 120 recently updated nodes and 240 associations. It does not accept a `limit` query parameter. The repository orders and limits nodes in SQL before loading associations inside that snapshot; it no longer decodes every Artifact or queries edges per node. A count query supplies `total`. No database index is added: very large libraries still incur a sorting scan and require measurement at representative scale.

Search and kind/time/scope/subject filters operate only on this snapshot. Loading or refreshing reads one snapshot of at most 120 nodes. Display defaults to 80 nodes, with 40/80/120 options. Changing the selection is local and does not trigger another request or prefetch a larger snapshot. The sphere mesh is decorative; selected associations and neighborhood isolation use real graph edges. The search drawer provides a keyboard list paginated at 30 rows, followed by focus, detail and audit actions. Reduced motion skips the entrance and continuous animations; a pause control also stops motion.

Saving a persona blueprint uses `crypto.getRandomValues` for random IDs on ordinary HTTP pages, without requiring secure-context `crypto.randomUUID`. Host login and API authentication remain required.
