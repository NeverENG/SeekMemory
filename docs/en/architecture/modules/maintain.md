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

relationship.py consumes original `relationship-v1` observations only after validating confidence, immutable Source existence, user-Source ownership, and one private/group/unknown scope. Private evidence weight is `1.0`; group and unknown are `0.5`. The pure rulebook separates counted IDs from reviewed IDs, caps repeated reasons per cycle, and limits one affinity revision to `0.10`. Maintenance commits the stable per-subject Relationship Artifact through expected-revision CAS, then updates Cache. `relationship_mode=off` skips consolidation; the default `observe` mode and explicit `enforce` both consolidate and persist the derived state. Observe mode may compute a candidate interaction profile, but reply denial still requires `relationship_mode=enforce` together with `runtime_gate_enabled=true`.

## Rules not connected to the production flow

reflect.py can compute wrong/right signals from adjacent user messages, but the current repository has no production caller. It is not an automatic reflection, memory-repair, or reinforcement path. Documentation and configuration must not present it as an enabled online feature.

## Interfaces and plan ownership

`maintain/domain.py` explicitly exports supported maintenance use cases and immutable `RevisionWrite` / `RevisionPlan` data. `maintain/ports.py` reuses existing Artifact/Source/cache protocols. Old imports and return values remain available. A `RevisionPlan` names one group transaction; distinct plans or relationship subjects are not collectively atomic. Resource construction/shutdown belongs to composition.

| Files | Responsibility and effects | Logical complexity and coupling |
|---|---|---|
| `decay.py`, `lifecycle.py` | Read active view → prepare group → commit → remove cached entries | Low: ordered I/O, one atomic group |
| `expiry_policy.py` | Existing retention and expiry revision decisions | Low/medium: supplied data, no repository calls |
| `merge.py`, `merge_policy.py` | Read subject/scope groups; cluster and prepare one create/retire group; commit and cache | Medium/high: each cluster is atomic; pure clustering/wording separate from I/O |
| `impression.py`, `impression_policy.py` | Read rivals, match and prepare old/new revisions; one atomic merge | Medium: subject/scope and evidence guards retained |
| `self_impression.py`, `self_impression_policy.py` | Read original paired evidence and referenced episodes; group observations and prepare revisions; commit then cache | High: exact immutable pairing and independent count ownership |
| `persona.py`, `persona_policy.py` | Read verified self-candidates, prepare seed-preserving persona and retire duplicates in one group | Medium: no user-private wording promoted to global persona |
| `relationship.py` | Orchestrate per-subject core plan, validation, CAS commit and cache | Medium: independent subject transactions |
| `relationship_evidence.py` | Read exact Source evidence and current state | Medium: reads only, rejects invalid identity/scope/confidence |
| `relationship_policy.py` | Prepare replacement payload/lineage and classify supplied evidence values | Low/medium: no I/O; core owns scoring policy |
| `link.py` | Optional bounded graph enhancement and legacy CAS persistence | Medium: optional edges separate from memory transactions |
| `reflect.py`, `promote.py` | Pure reflection signals (no production caller) and verified self-candidate compatibility entry | Low/medium: documented actual wiring |

The matching variants deliberately remain separate: impression Dice, merge/reflect Jaccard and graph-link Dice are not interchangeable. The existing impression dependency on the recall character helper is documented for the later shared-rule migration. No formulas, time conversion, seed contents, prompts or persisted formats change in this pass. Interface/import contracts and existing evidence, persona, identity, relationship and failure scenarios verify the moved stages.

## Prepared-write recovery

`MaintenanceService` retains one `MaintenanceWriter`. Each task prepares an exact `RevisionPlan`, then the writer uses the existing single or group transaction. Failed database writes retain that exact plan/IDs; CAS conflicts discard it without rebasing or overwriting newer content. Successful commits are recorded and consumed before cache work. Cache-only repair tracks committed IDs and reads their newest database heads; it never repeats a version commit.

Before deriving new plans from cache, the writer retries unfinished work. A still-unrepaired view reports `maintenance_writeback_pending`, preventing stale-cache recreation of self-impressions or parallel personas. Service outcomes include `writeback_pending` counts where a final cache repair remains; pure background compensation and shutdown can retry without model/policy execution. Model-synthesized persona drafts also use this writer, so a failed commit can be repaired without another model request. Rebinding the existing caller-owned repository/cache fields keeps prepared progress and uses the current resources.

Free functions accept an optional keyword writer. Existing callers keep their return shapes and propagation of cache failures; long-lived services inject the retained writer and defer cache-only errors. Distinct group/subject plans remain independent transactions. Recovery is process-local; no persistent task tables or crash/multiprocess guarantee is added. The known duplicate cache-repair implementations are scheduled for the cross-module shared-capability pass.

`tests/test_maintenance_failure_recovery.py` covers exact failed-plan IDs, repeated cache failures with newer versions, no parallel personas, conflicting-group atomicity and no repeated persona model calls. Reverting the recovery commit needs no data migration.
