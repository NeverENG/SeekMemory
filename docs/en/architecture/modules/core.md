# core: Domain Objects and Pure Policies

## Responsibility

core defines the stable vocabulary and I/O-free decisions of the memory domain. It does not own SQL, cache, model calls, networking, or AstrBot events.

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

Family validators live in core/families. make constructs an object but does not validate it; production callers explicitly invoke validate before commit. revise retains ID and family, increments revision, and refreshes updated time.

## Pure policies

- **strength.py** computes retention, decay weight, and recall/spoken/confirmed reinforcement. Explicit hits take precedence; older data may derive effective hits from weight.
- **versioning.py** checks stable ID/family, contiguous revision, and created time; it defines state events and semantic-change detection.
- **disclosure.py** combines context affinity, subject fit, scope prior, sensitivity, and relevance into full, paraphrase, hint, or silence. Only full may return raw Artifact content; lower levels use fixed generic text. The sensitivity of the secret family prevents disclosure.
- **graph.py / tree.py** use injected repository protocols for relation edges and parent/child structure. They do not issue SQL. Causal edges have an explicit API but no automatic semantic inference.
- **capacity.py** converts a capacity snapshot and configurable thresholds into a state and scheduler actions as a pure decision; services perform the actions.
- **trace.py** sanitizes run-trace fields and projects event timelines while restricting stored data.

## Core invariants

Sources are append-only facts; Artifacts are revisable interpretations. Content updates go through ArtifactStore with expected_revision and cannot overwrite version history. subject_id, said_by, source session, and evidence must not be inferred in place of one another. Family validators own payload shape.

Implementation: [artifact.py](../../../../core/artifact.py), [source.py](../../../../core/source.py), [disclosure.py](../../../../core/disclosure.py), [versioning.py](../../../../core/versioning.py).
