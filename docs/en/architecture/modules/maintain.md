# maintain: Lifecycle and Persona Consolidation

## Responsibility

maintain applies lifecycle transitions, similarity merges, impression revisions, relation linking, and self-persona consolidation to committed Artifacts. MaintenanceService orchestrates weekly work; policies remain deterministic where possible and write through ArtifactStore.

## Lifecycle and merging

- decay.py processes active memory only and skips fact. Other memory levels use strength, shape, and time to calculate retention; low-retention items become forgotten revisions. Other Artifact families do not use this decay rule.
- lifecycle.py marks active Artifacts forgotten when expires / valid_to has passed. Sources and version history remain intact.
- merge.py checks the oldest candidate batch only when active scene/detail count exceeds 500. It first isolates candidates by subject_id and scope, then clusters on character-bigram similarity; a cluster needs at least three members to create an impression. The new Artifact records member IDs in derived_from and members become merged. commit_many writes the group atomically.
- impression.py compares a new impression only with active impressions for the same subject and scope. Near-identical wording merges evidence and reinforces the existing node; a more complete wording adds a revision on the same ID and retires the duplicate candidate. Both changes commit atomically through commit_many as merge operations, with the reason distinguishing reinforcement from rewording; the cache changes only after commit. Write failures and revision conflicts propagate to the service layer, preserving both pre-consolidation records and cache entries.
- link.py creates a bounded number of similar / temporal edges between active memory in the same scope. Causal edges are not inferred automatically.

## Bot self-impressions and persona

self_impression.py aggregates only six fixed bot_behavior values. Each scene must point to an actual assistant Source and the same-session user parent verified by reply_to. Distinct assistant Sources count as distinct observations. After at least three observations with confidence at or above 0.9, the system revises one stable shared self-impression per behavior. Shared text comes from fixed templates, not user-specific free text.

persona.py selects at most three behavior categories from trusted self-impressions. A seeded persona evolves on the same Artifact ID and retains evidence and version history. MaintenanceService may run one bounded model synthesis when an eligible bootstrapped persona reaches its interval; failure keeps the previous persona. Older unseeded installations may use a deterministic compatibility path. See the [persona seed guide](../../guides/persona-seed.md).

## Relationship consolidation

Weekly maintenance first queues V1 memory versions with attributable, timezone-aware Sources as idempotent pending events while retaining old Artifacts, then independently verifies up to 24 pending candidates. Model failures leave them pending; only verified events enter replay. `relationship.py` rechecks source identity, session, timezone, and scope; unzoned, unattributable, and unknown-scope rows do not score. An explicit clock projects each subject into a stable V2 Artifact committed with expected-revision CAS, revision-scoped Source evidence, and V1 memory provenance. Cache updates only after commit; deactivated relationships stay inactive and identical inputs/clocks do not create duplicate versions. `relationship_mode=off` skips this path; `observe` and the legacy config value `enforce` currently observe only.

Weekly verification selects at most 24 due events for the current verifier version. A model/provider failure keeps the candidate pending and persists a bounded exponential retry time (one minute to one day); deferred entries move behind eligible untouched work even across restarts. Confirmed missing Source references and malformed candidate fields abstain rather than retry indefinitely. A failure to persist the retry is surfaced instead of claiming recovery.

## Rules not connected to the production flow

reflect.py can compute wrong/right signals from adjacent user messages, but the current repository has no production caller. It is not an automatic reflection, memory-repair, or reinforcement path. Documentation and configuration must not present it as an enabled online feature.

`dream_reconcile.py` only prepares an offline explicit-correction example: a same-private-session user Source replies to the original evidence with a “更正：”/“Correction:” marker, and the sole identical parent impression depends entirely on one fact child. It prepares one atomic revision plan to revise the child and deactivate that parent. This module neither commits data nor changes tree edges, and it is not wired into Dream or Runtime; multiple parents, other phrasing and complex narratives defer rather than implying automatic correction is enabled.

`MaintenanceWriter.execute_tree` accepts an externally reviewed multi-parent tree change and atomically submits its heads and edges via `ArtifactRepository.commit_tree_change`. It repairs cache from current database heads after commit; replaying an operation ID does not count new writes. The existing `dream_reconcile.py` still prepares a single-parent revision-only example and is not automatically promoted to a tree write. Automatic Dream correction and a multi-parent decision maker remain absent.

`dream_impact.py` offers an offline, read-only correction impact inspection: starting from a child, it compares raw tree edges with current active `derived_from` references within depth, parent, visit and evidence limits. Only paths corroborated by both records and matching identity, scope, visibility and existing Source references and current-revision evidence contribute affected parent IDs. Missing links, retired nodes, cycles, unsupported evidence or truncation produce blocker reasons. The report contains no message text, never authorizes a write and is not scheduled by Dream. Storage only reads existing `nodes.lineage` for bounded reverse dependencies; it changes no stored structure.

## Interfaces and plan ownership

`maintain/domain.py` explicitly exports supported maintenance use cases and immutable `RevisionWrite` / `RevisionPlan` data. `maintain/ports.py` reuses existing Artifact/Source/cache protocols and declares the read-only store capability for offline impact inspection. Unrelated maintenance imports and return values remain available; retired V1 relationship helpers are removed. A `RevisionPlan` names one group transaction; distinct plans or relationship subjects are not collectively atomic. Resource construction/shutdown belongs to composition.

| Files | Responsibility and effects | Logical complexity and coupling |
|---|---|---|
| `decay.py`, `lifecycle.py` | Read active view → prepare group → commit → remove cached entries | Low: ordered I/O, one atomic group |
| `expiry_policy.py` | Existing retention and expiry revision decisions | Low/medium: supplied data, no repository calls |
| `merge.py`, `merge_policy.py` | Read subject/scope groups; cluster and prepare one create/retire group; commit and cache | Medium/high: each cluster is atomic; pure clustering/wording separate from I/O |
| `impression.py`, `impression_policy.py` | Read rivals, match and prepare old/new revisions; one atomic merge | Medium: subject/scope and evidence guards retained |
| `self_impression.py`, `self_impression_policy.py` | Read original paired evidence and referenced episodes; group observations and prepare revisions; commit then cache | High: exact immutable pairing and independent count ownership |
| `persona.py`, `persona_policy.py` | Read verified self-candidates, prepare seed-preserving persona and retire duplicates in one group | Medium: no user-private wording promoted to global persona |
| `relationship.py` | Queue attributable V1 versions for independent verification; replay verified Source events into per-subject V2 revisions through CAS and cache repair | Medium: independent subject transactions and no fabricated evidence |
| `link.py` | Optional bounded graph enhancement and legacy CAS persistence | Medium: optional edges separate from memory transactions |
| `reflect.py`, `promote.py` | Pure reflection signals (no production caller) and verified self-candidate compatibility entry | Low/medium: documented actual wiring |

The matching variants deliberately remain separate: impression Dice, merge/reflect Jaccard and graph-link Dice are not interchangeable. Impression matching uses the shared alphanumeric rule in app; relationship V2 uses its own verified, time-aware projection. Existing non-relationship matching and seed rules are unchanged by this integration.

## Prepared-write recovery

`MaintenanceService` retains one `MaintenanceWriter`. Each task prepares an exact `RevisionPlan`, then the writer uses the existing single or group transaction. Failed database writes retain that exact plan/IDs; CAS conflicts discard it without rebasing or overwriting newer content. Successful commits are recorded and consumed before cache work. Cache-only repair tracks committed IDs and reads their newest database heads; it never repeats a version commit.

Before deriving new plans from cache, the writer retries unfinished work. A still-unrepaired view reports `maintenance_writeback_pending`, preventing stale-cache recreation of self-impressions or parallel personas. Service outcomes include `writeback_pending` counts where a final cache repair remains; pure background compensation and shutdown can retry without model/policy execution. Model-synthesized persona drafts also use this writer, so a failed commit can be repaired without another model request. Rebinding the existing caller-owned repository/cache fields keeps prepared progress and uses the current resources.

Free functions accept an optional keyword writer. Existing callers keep their return shapes and propagation of cache failures; long-lived services inject the retained writer and defer cache-only errors. Distinct group/subject plans remain independent transactions. Recovery is process-local; no persistent task tables or crash/multiprocess guarantee is added. Committed-ID repair is delegated to the shared app capability; the writer retains semantic plans only.

`tests/test_maintenance_failure_recovery.py` covers exact failed-plan IDs, repeated cache failures with newer versions, no parallel personas, conflicting-group atomicity and no repeated persona model calls. Reverting the recovery commit needs no data migration.

Committed-ID cache repair is shared through `app.CacheRepairs`; the composition root injects the same instance into checkpoint, extraction, context and maintenance writers. Business plans remain with each use case, and per-owner counts keep unrelated repairs out of checkpoint pending totals.
