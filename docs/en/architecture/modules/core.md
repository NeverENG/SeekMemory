# core: Domain Objects and Pure Policies

## Responsibility

core defines the stable vocabulary and I/O-free decisions of the memory domain. It does not own SQL, cache, model calls, networking, or AstrBot events.

## Provided domain and required-port entries

The module separates the capabilities it provides from those callers must supply. Both entries contain explicit exports or protocol declarations with mixed English/Chinese behavior notes and no business implementation:

- **Provided capabilities — [`core/domain.py`](../../../../core/domain.py)**: domain values and operations for Artifact construction/revision/validation, Source identity, version checks, strength, disclosure, graph, capacity, persona, relationship/interaction, and trace projection. Functions and types retain their original identities; their complete call signatures remain available in their definitions or through `inspect.signature()`. There are no wrapper functions or empty implementations.
- **Required capabilities — [`core/ports.py`](../../../../core/ports.py)**: edge storage through `GraphArtifactStore`. Each method describes results, read/write effects, and necessary failure guarantees. Implementations are injected; callers own connection lifetimes.

Callers use `from core.domain import make, Graph` for provided capabilities and `from core.ports import GraphArtifactStore` for required capabilities, or equivalent relative imports inside the plugin package. Domain implementation paths such as `core.artifact` and `core.graph` remain valid; `core.graph.GraphArtifactStore` aliases the port declaration. Graph imports `ports.py` directly, allowing `domain.py` to export graph types normally without lazy binding. The internal `core.interfaces` entry has been removed.

Tree read/write orchestration belongs to [TreeService](services.md), imported internally with `from services import TreeService`; `core.tree` and core's tree exports have been removed. Its required `TreeArtifactStore` and `TreeCache` declarations live in `app/ports.py`; core does not import the application or service layer.

`make`/`revise` still read the system clock, and `load_thresholds` still reads environment variables. `Graph` invokes injected edge storage; `edges_of` queries both ends but omits original direction.

## Data model

- **Source** is an immutable value for one original message. make_source_id derives a stable ID from a host event ID or from session, speaker, role, time, and text. Validation requires an ID, supported role, and non-empty text.
- **Artifact** consists of a Header and a family-specific payload. The Header contains ID, family, revision, state, scope, lineage, strength, time, said_by, shareable, and subject_id.
- **Lineage** uses sources for original evidence and derived_from for the upstream Artifacts behind an abstraction. They serve different purposes.
- **TimeSpan** carries created, updated, and validity fields. Extraction may use event time for created; recall/temporal applies validity during reads.

Family and memory level are separate dimensions:

| Family | Purpose and payload entry point |
|---|---|
| memory | text plus one of four levels: fact, scene, detail, impression; may include shape, chrono, about, tags, and behavior evidence |
| persona | active persona text and seed/Dream provenance |
| example | user/assistant dialogue example |
| media | type, title, url, with optional summary/shared_by |
| secret | protected ref and shadow_text; excluded by the recall candidate filter |
| designated | explicit delivery text, trigger, and given state |
| relationship | versioned per-subject affinity, confidence, evidence count, hysteretic band, and a content-free policy snapshot; excluded from Recall |

Family validators live in core/families. make constructs an object but does not validate it; production callers explicitly invoke validate before commit. revise retains ID and family, increments revision, and refreshes updated time.

## Pure policies

- **strength.py** computes retention, decay weight, and recall/spoken/confirmed reinforcement. Explicit hits take precedence; older data may derive effective hits from weight.
- **versioning.py** checks stable ID/family, contiguous revision, and created time; it defines state events and semantic-change detection.
- **disclosure.py** combines context affinity, subject fit, scope prior, sensitivity, and relevance into full, paraphrase, hint, or silence. Only full may return raw Artifact content; lower levels use fixed generic text. The sensitivity of the secret family prevents disclosure.
- **graph.py** uses an injected repository protocol for relation edges and does not issue SQL. Causal edges have an explicit API but no automatic semantic inference.
- **capacity.py** converts a capacity snapshot and configurable thresholds into a state and scheduler actions as a pure decision; services perform the actions.
- **trace.py** sanitizes run-trace fields and projects event timelines while restricting stored data.
- **relationship.py / relationship_rules.py** own stable relationship IDs, snapshots, hysteresis, the ten-reason evidence rulebook, scope weights, per-cycle caps, and bounded revision plans. Models classify observations but never write affinity, delta, band, or policy version.
- **interaction_policy.py** produces deterministic reply probability, fixed style, affection/follow-up/care/teasing permissions, and future proactive-kind permissions. Sampling is stable by immutable Source ID and fails open when the ID is absent.

## Constant and policy-parameter ownership

Constants stay with the rules they belong to; there is no global constants file. Equal numbers do not imply equal meaning: relationship confidence and close-band admission thresholds remain independent.

| Category | Canonical owner and use |
|---|---|
| Internal algorithm parameters | Emotion factors, salience bounds and the hit factor belong to `strength.py`; disclosure thresholds and factors to `disclosure.py`; relationship entry/exit thresholds to `relationship.py`; confidence smoothing to `relationship_rules.py`. Named parameters live near the top of each file. New private names are neither exported from `domain.py` nor exposed as user configuration. |
| Existing configurable policy values | `CapacityThresholds`, `RelationshipScoringPolicy` and `InteractionPolicySettings` retain their respective parameters and defaults. The fixed interaction rule table reuses the default probabilities from `InteractionPolicySettings`; configuration parsing and default consolidation in other layers are outside core constant ownership. |
| Data contracts | Family names, Source roles, operation names and persona origins retain their domain owners. `relationship.py` owns relationship bands and its policy-version identifier, imported by the family validator. Trace derives allowed disclosure values from `DisclosureLevel`. Persisted values and their order are unchanged. |
| Validation and diagnostic limits | Persona file size limits remain in `persona.py`, self-impression trust requirements in `bot_behavior.py`, and trace count limits/allowlists in `trace.py`. |

Existing public constants keep their exports. Ownership cleanup does not change values, comparison boundaries, evaluation order, configuration-read timing or algorithm results.

## Core invariants

Sources are append-only facts; Artifacts are revisable interpretations. Content updates go through ArtifactStore with expected_revision and cannot overwrite version history. subject_id, said_by, source session, and evidence must not be inferred in place of one another. Family validators own payload shape.

Implementation: [artifact.py](../../../../core/artifact.py), [source.py](../../../../core/source.py), [disclosure.py](../../../../core/disclosure.py), [versioning.py](../../../../core/versioning.py).
