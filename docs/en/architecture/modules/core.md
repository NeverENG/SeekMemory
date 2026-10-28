# core: Domain Objects and Pure Policies

## Responsibility

core defines the stable vocabulary and I/O-free decisions of the memory domain. It does not own SQL, cache, model calls, networking, or AstrBot events.

## Single interface entry

[`core/interfaces.py`](../../../../core/interfaces.py) is the module's single primary interface file. It contains declarations, explicit exports, and mixed English/Chinese behavior notes, with no business implementation. It separates:

- **Provided capabilities**: domain values and operations for Artifact construction/revision/validation, Source identity, version checks, strength, disclosure, graph/tree, capacity, persona, relationship/interaction, and trace projection. Functions and types retain their original identities; their complete call signatures remain available in their definitions or through `inspect.signature()`. There are no wrapper functions or empty implementations.
- **Required capabilities**: edge storage through `GraphArtifactStore`, Artifact/version/parent storage through `TreeArtifactStore`, and optional active-memory caching through `TreeCache`. Each method describes results, read/write effects, and necessary failure guarantees. Implementations are injected; callers own connection and cache lifetimes.

New callers can use `from core.interfaces import make, Graph, TreeArtifactStore`, or the equivalent relative imports inside the plugin package. Existing `core.artifact`, `core.graph`, `core.tree`, and other imports remain valid. The three previous protocol names alias the centralized declarations. Only the private `_interface_bindings.py` handles lazy imports of `Graph`, `Tree`, and related values, avoiding cyclic initialization while graph/tree load their protocol declarations. That file is neither another interface surface nor a business implementation.

Centralizing the interface preserves existing behavior: `make`/`revise` still read the system clock, and `load_thresholds` still reads environment variables. `Graph`/`Tree` invoke injected storage/cache operations; the commit, cache, parent-column, and edge updates in `Tree.add_under` are not one transaction. `edges_of` queries both ends but omits original direction; `set_parent` changes only the parent column, not edges. A cache miss does not prove database absence, and `put` does not persist data.

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
- **graph.py / tree.py** use injected repository protocols for relation edges and parent/child structure. They do not issue SQL. Causal edges have an explicit API but no automatic semantic inference.
- **capacity.py** converts a capacity snapshot and configurable thresholds into a state and scheduler actions as a pure decision; services perform the actions.
- **trace.py** sanitizes run-trace fields and projects event timelines while restricting stored data.
- **relationship.py / relationship_rules.py** own stable relationship IDs, snapshots, hysteresis, the ten-reason evidence rulebook, scope weights, per-cycle caps, and bounded revision plans. Models classify observations but never write affinity, delta, band, or policy version.
- **interaction_policy.py** produces deterministic reply probability, fixed style, affection/follow-up/care/teasing permissions, and future proactive-kind permissions. Sampling is stable by immutable Source ID and fails open when the ID is absent.

## Core invariants

Sources are append-only facts; Artifacts are revisable interpretations. Content updates go through ArtifactStore with expected_revision and cannot overwrite version history. subject_id, said_by, source session, and evidence must not be inferred in place of one another. Family validators own payload shape.

Implementation: [artifact.py](../../../../core/artifact.py), [source.py](../../../../core/source.py), [disclosure.py](../../../../core/disclosure.py), [versioning.py](../../../../core/versioning.py).
