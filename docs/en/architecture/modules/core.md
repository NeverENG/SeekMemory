# core: Domain Objects and Pure Policies

## Responsibility

core defines the stable vocabulary and I/O-free decisions of the memory domain. It does not own SQL, cache, model calls, networking, or AstrBot events.

The central entry also exports upstream persona-pack/artwork validation, format identifiers and size limits (`normalize_pack`, `validate_artwork`, and related values) without changing those pure implementations.

## Provided domain and required-port entries

The module separates the capabilities it provides from those callers must supply. Both entries contain explicit exports or protocol declarations with mixed English/Chinese behavior notes and no business implementation:

- **Provided capabilities — [`core/domain/`](../../../../core/domain/)**: domain values and operations for Artifact construction/revision/validation, Source identity, version checks, strength, disclosure, graph, capacity, persona, relationship/interaction, and trace projection. Functions and types retain their original identities; their complete call signatures remain available in their definitions or through `inspect.signature()`. There are no wrapper functions or empty implementations.
- **Required capabilities — [`core/port/`](../../../../core/port/)**: edge storage through `GraphArtifactStore` and read-only tree edges through `TreeEdgeReader`. Each method describes results, read/write effects, and necessary failure guarantees. Implementations are injected; callers own connection lifetimes.

Callers use `from core.domain import make, Graph` for provided capabilities and `from core.port import GraphArtifactStore` for required capabilities, or equivalent relative imports inside the plugin package. Domain implementations are grouped under `core/domain/`, and the graph storage protocol lives in `core/port/graph.py`. Old paths such as `core.artifact`, `core.graph`, and `core.ports` remain compatibility entries; `core.graph.GraphArtifactStore` is the same port object. The package entry points export capabilities rather than implementing business logic; new code should import the owning domain module or `core.port`. The internal `core.interfaces` entry remains removed.

Tree read/write orchestration belongs to [TreeService](services.md), imported internally with `from services import TreeService`; `core.tree` and core's tree exports have been removed. Its required `TreeArtifactStore` and `TreeCache` declarations live in `app/ports.py`; core does not import the application or service layer.

`make`/`revise` still read the system clock, and `load_thresholds` still reads environment variables. `Graph` invokes injected edge storage; `edges_of` queries both ends but omits original direction.

Model calls do not belong in `core.port`: `app.ports.ChatModel` owns the extraction-model contract, `app.runtime.contracts.ModelGateway` owns runtime text generation, and AstrBot providers are adapted at the edge. This directory move does not change model selection or call behavior.

`core/domain/memory/tree.py` queries every encoded parent through bounded directed `tree_child:<parent ID>` edges; breadth-first ancestry has independent depth, parent fan-out, and visit limits, and deduplicates cycles. `TreeService` accepts multiple parent IDs per child, validates their identity and state, and commits the Artifact revision and tree edges in one transaction. The historical single-value `nodes.parent` column remains in the existing schema but is no longer written or read as a tree relation. No automatic migration runs; a missing edge for a legacy-only parent causes enabled tree recall to fall back to flat recall.

Domain implementations are grouped under `core/domain/memory/` (evidence, versioning, retrieval, disclosure), `character/` (persona), `social/` (relationships and interaction), and `operations/` (capacity and trace). `core/families/` retains payload validation; `core/port/` declares only the graph-storage capability actually required by the domain. `core.domain` retains the stable exported API; historical `core.<module>` and `core.domain.<module>` paths resolve to the same implementation modules. Application runtime contracts remain in `app/runtime/contracts/` rather than being moved into memory-domain ports.

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
| relationship | versioned per-subject familiarity, trust, warmth, tension, stability, and confidence; excluded from Recall and reply gating during V2 observation |

Family validators live in core/families. make constructs an object but does not validate it; production callers explicitly invoke validate before commit. revise retains ID and family, increments revision, and refreshes updated time.

## Pure policies

- **strength.py** computes retention, decay weight, and recall/spoken/confirmed reinforcement. Explicit hits take precedence; older data may derive effective hits from weight.
- **versioning.py** checks stable ID/family, contiguous revision, and created time; it defines state events and semantic-change detection.
- **disclosure.py** combines context affinity, subject fit, scope prior, sensitivity, and relevance into full, paraphrase, hint, or silence. Only full may return raw Artifact content; lower levels use fixed generic text. The sensitivity of the secret family prevents disclosure. `PrivacyPolicy` binds the existing scope prior, decision, and safe wording into an injectable pure strategy; its default instance changes no formula, threshold, or public configuration.
- **graph.py** uses an injected repository protocol for relation edges and does not issue SQL. Causal edges have an explicit API but no automatic semantic inference.
- **capacity.py** converts a capacity snapshot and configurable thresholds into a state and scheduler actions as a pure decision; services perform the actions.
- **trace.py** sanitizes run-trace fields and projects event timelines while restricting stored data.
- **relationship.py / relationship_rules.py** own stable IDs, ten candidate reasons, and multidimensional snapshots. Replay consumes only same-subject, timezone-aware, independently verified Source events: private weight 1.0, group weight 0.5, mild/strong factors 1/2, learning rate 0.25. Familiarity decays over 180 days, confidence and repeated-evidence stability over 90; warmth and trust use 45/180-day half-lives and `tanh` bounds. Tension cools with a 14-day half-life after 24 hours; only a repair linked to an earlier verified negative can reduce its tension, capped at 75% without repeated subtraction. Sources are counted once; models propose candidates and semantic verdicts, not dimensions or scores.
- V2 has no single favorability score. Even with legacy `enforce` config, relationship observation cannot change replies or tone; the Runtime gate stays independent.

## Constant and policy-parameter ownership

Constants stay with their owning rules; relationship V2 evidence weights, half-lives and cooldown are independent of memory disclosure thresholds.

| Category | Canonical owner and use |
|---|---|
| Internal algorithm parameters | Emotion factors and salience bounds belong to `strength.py`; disclosure thresholds to `disclosure.py`; relationship V2 evidence impact, decay and cooldown to `relationship_rules.py`. New private names are not automatically exported from `domain.py` or exposed as configuration. |
| Existing configurable policy values | `CapacityThresholds` and `RelationshipScoringPolicy` retain their respective parameters; relationship configuration is normalized by the service layer. V1 interaction rules and relationship reply gates are retired. |
| Data contracts | Family names, Source roles, operation names and persona origins retain their domain owners. `relationship.py` owns the V2 snapshot and policy identifier; family validation still accepts historical V1 payloads without promoting their affinity to V2. Trace derives allowed disclosure values from `DisclosureLevel`. |
| Validation and diagnostic limits | Persona file size limits remain in `persona.py`, self-impression trust requirements in `bot_behavior.py`, and trace count limits/allowlists in `trace.py`. |

Unrelated public constants retain their exports. V2 replaces V1 band and interaction exports rather than preserving obsolete scoring behavior.

## Core invariants

Sources are append-only facts; Artifacts are revisable interpretations. Content updates go through ArtifactStore with expected_revision and cannot overwrite version history. subject_id, said_by, source session, and evidence must not be inferred in place of one another. Family validators own payload shape.

Implementation: [artifact.py](../../../../core/domain/memory/artifact.py), [source.py](../../../../core/domain/memory/source.py), [disclosure.py](../../../../core/domain/memory/disclosure.py), [versioning.py](../../../../core/domain/memory/versioning.py).

<a id="core-verification"></a>

## Verification entry points and evidence limits

These are entry points into existing tests, not proof of complete coverage for every exported name. Pure rules and cross-module flows use separate files. [tests/layers.py](../../../../tests/layers.py) prioritizes explicit layer suffixes over legacy names; a layer does not mean “core only”. The map below identifies each capability’s evidence owner.

| Capability | Current test entry points | Evidence and limits |
|---|---|---|
| Provided domain and required-port entries | [test_core_interface_contract.py](../../../../tests/test_core_interface_contract.py) | Export identities, declarations without business implementations, port call shapes, dependency direction and import orders; not complete behavioral coverage of every exported operation. |
| Artifact construction, revision and family validation | [test_artifact.py](../../../../tests/test_artifact.py) | Required fields, defaults, readable content and revision without mutating the original; no database transaction verification. |
| Source, versions and commits | [test_kernel_integration.py](../../../../tests/test_kernel_integration.py) | [test_kernel_unit.py](../../../../tests/test_kernel_unit.py) checks pure Source identity, version and disclosure rules; the integration file checks SQLite atomic commits, checkpoint and migrations. |
| Retention, decay and reinforcement | [test_strength.py](../../../../tests/test_strength.py), [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py) | Retention over time, emotion thresholds, reinforcement increments and cooldown; not long-term memory quality in real conversations. |
| Disclosure and privacy output | [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py), [test_kernel_unit.py](../../../../tests/test_kernel_unit.py), [test_privacy_outputs.py](../../../../tests/test_privacy_outputs.py) | Threshold boundaries, cross-session disclosure and protected content in final context; final-output checks span core and recall. |
| Graph links | [test_link_integration.py](../../../../tests/test_link_integration.py) | The integration file retains SQLite, cache and associative linking; [test_graph_unit.py](../../../../tests/test_graph_unit.py) checks causal links, degree, filtering and weights through a small storage-port fake. |
| Capacity decisions | [test_capacity_unit.py](../../../../tests/test_capacity_unit.py) | Pressure states, scheduler actions and configuration overrides; queue, persistence and recovery flows live in [test_capacity_integration.py](../../../../tests/test_capacity_integration.py). |
| Persona and self-impression trust | [test_persona.py](../../../../tests/test_persona.py), [test_persona_bootstrap.py](../../../../tests/test_persona_bootstrap.py), [test_self_impression.py](../../../../tests/test_self_impression.py) | Persona initialization, evidence constraints and trusted results after maintenance; includes cross-module flows, not proof that a real model forms an appropriate persona. |
| Relationship V2 replay and verification | [test_relationship_unit.py](../../../../tests/test_relationship_unit.py), [test_relationship_integration.py](../../../../tests/test_relationship_integration.py), [test_relationship_verifier.py](../../../../tests/test_relationship_verifier.py), [test_store.py](../../../../tests/test_store.py) | Deterministic clock replay, candidate separation, semantic verification and versioned Source-backed persistence; these fixtures do not measure real-model false-positive rates or real AstrBot behavior. |
| Run tracing | [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py), [test_run_trace.py](../../../../tests/test_run_trace.py) | Disclosure vocabulary, count limits, and content exclusion/recovery after trace persistence; the latter is a trace integration check. |

Run focused interface and common domain-rule checks from the repository root:

```bash
python tests/test_core_interface_contract.py
python tests/test_core_policy_contract.py
python tests/test_artifact.py
python tests/test_strength.py
```

For version commits, disclosure or complete data paths, add checks relevant to the change:

```bash
python tests/test_kernel_integration.py
python tests/test_e2e_kernel.py
python tests/test_privacy_outputs.py
```

These commands are not a fixed minimum for every core change and do not replace the capability-specific checks above. Repository-wide layer commands and selection guidance are in [Development Setup and Checks](../../guides/development.md). A pass establishes only the assertions in the scenarios executed; it does not establish real-model extraction quality, real AstrBot host compatibility or improved memory quality.

## Using benchmarks to verify core

[Fixed memory regression](../../../../benchmarks/README.md) combines core, recall and storage rather than covering every core capability independently. `benchmarks/run.py` fixes fixtures, dates, IDs and configuration and compares pre-cleanup and target code per query. JSON records pass/fail and regressions return nonzero. Ordinary output uses a new run directory without overwriting historical reports.

Candidate/final-context hits, no-answer false positives, candidate noise including negatives and character counts are separate. The full pipeline checks privacy and positive disclosure controls. Retention samples call actual retention without executing nightly maintenance; fixture-weight ratios do not call reinforce or establish reinforcement correctness. Characters are not tokenizer tokens or cost, and the old personality composite remains historical only.

`benchmarks/bm25.py` retains independent frozen data and gates. Reports record code, evaluator, corpus and environment; timing is environment-dependent description. A pass means no regression relative to the fixed baseline, not absence of existing false positives, and does not replace real-model or host acceptance.

Explicit pack association and fallback rules are described in [WebUI](webui.md#persona-studio-and-application-baselines). `core/domain/character/persona_application.py` owns canonical content/settings/artwork digests and read projection of optional application metadata, without file I/O or guessing associations from legacy seed IDs. Name, text, style and boundary changes are compared separately from pack assets.
