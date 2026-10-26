# WebUI: Management API and Dashboard

## Layers

- webui/routes.py registers AstrBot plugin routes and handles authentication, method/body limits, status mapping, and service calls.
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
