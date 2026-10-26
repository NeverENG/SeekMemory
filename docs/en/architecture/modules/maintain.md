# maintain: Lifecycle and Persona Consolidation

## Responsibility

maintain applies lifecycle transitions, similarity merges, impression revisions, relation linking, and self-persona consolidation to committed Artifacts. MaintenanceService orchestrates weekly work; policies remain deterministic where possible and write through ArtifactStore.

## Lifecycle and merging

- decay.py processes active memory only and skips fact. Other memory levels use strength, shape, and time to calculate retention; low-retention items become forgotten revisions. Other Artifact families do not use this decay rule.
- lifecycle.py marks active Artifacts forgotten when expires / valid_to has passed. Sources and version history remain intact.
- merge.py checks the oldest candidate batch only when active scene/detail count exceeds 500. It first isolates candidates by subject_id and scope, then clusters on character-bigram similarity; a cluster needs at least three members to create an impression. The new Artifact records member IDs in derived_from and members become merged. commit_many writes the group atomically.
- impression.py compares a new impression only with active impressions for the same subject and scope. Near-identical wording merges evidence and reinforces the existing node; a more complete wording adds a revision on the same ID and retires the duplicate candidate.
- link.py creates a bounded number of similar / temporal edges between active memory in the same scope. Causal edges are not inferred automatically.

## Bot self-impressions and persona

self_impression.py aggregates only six fixed bot_behavior values. Each scene must point to an actual assistant Source and the same-session user parent verified by reply_to. Distinct assistant Sources count as distinct observations. After at least three observations with confidence at or above 0.9, the system revises one stable shared self-impression per behavior. Shared text comes from fixed templates, not user-specific free text.

persona.py selects at most three behavior categories from trusted self-impressions. A seeded persona evolves on the same Artifact ID and retains evidence and version history. MaintenanceService may run one bounded model synthesis when an eligible bootstrapped persona reaches its interval; failure keeps the previous persona. Older unseeded installations may use a deterministic compatibility path. See the [persona seed guide](../../guides/persona-seed.md).

## Rules not connected to the production flow

reflect.py can compute wrong/right signals from adjacent user messages, but the current repository has no production caller. It is not an automatic reflection, memory-repair, or reinforcement path. Documentation and configuration must not present it as an enabled online feature.
