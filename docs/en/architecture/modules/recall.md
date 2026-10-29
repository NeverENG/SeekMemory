# recall: Retrieval, Disclosure, and Prompt Assembly

## Responsibility

recall selects active Artifacts relevant to the current input, decides what can be said in the current context, and returns a character-bounded text block with decision metadata. It makes no model calls and does not issue SQL directly; graph edges, history, and Source lookup may read through injected repositories.

## Execution order

1. pipeline resolves the current speaker/owner and reads active Artifacts from Cache.
2. scope.visible excludes family=secret; designated records are limited to their owning conversation. Ordinary memory with private, shared, or shadow scope is not hard-filtered by origin session; scope influences later disclosure strength. Private does not guarantee that cross-session text will be quoted.
3. Validity and explicit time-window filters remove expired or out-of-window memory. Designated also requires a private chat, a matching trigger, and no previous delivery.
4. For memory intent, a Retriever returns candidates: GraphRetriever uses character-bigram seeds and graph activation; HybridRetriever adds local BM25 lexical evidence. BM25 indexes body and tags separately and computes statistics from the current visible pool. It adds no model, network, or SQL call.
5. select scores literal, tag, emotion, activation, and lexical evidence, then applies an absolute/relative evidence gate. Weight, freshness, and recent-use status help rank candidates but cannot let an irrelevant item pass on their own.
6. Explicit profile/topic recall may use a recent-memory fallback; when no candidates were selected, eligible inputs may use one deterministic drift candidate.
7. If ordinary selection returns fewer than min(2, recall_k) items and the query has memory intent, a bounded recent Source fallback may run. It uses Source IDs to query Artifacts with evidence on their current revision, then repeats visibility, validity, and disclosure checks. Source text is never assembled.
8. After disclosure, assemble orders persona, impression, scene, detail, fact, and example content, applies the budget, and returns final_ids / dropped_ids.

Source fallback recency compares absolute instants for offset-aware timestamps; naive timestamps retain local wall-time comparison in the runtime's timezone. Original Sources are not rewritten.

## Disclosure and delivery

core.disclosure combines context affinity, subject fit, scope prior, sensitivity, and relevance into full, paraphrase, hint, or silence. Lower than full uses fixed generic sentences, not the original text or tags. Being selected does not mean an item made the final block; injection does not prove that the model used it.

family=secret never enters the ordinary candidate pool. A memory with scope=shadow can only use a masked expression. family=designated has a separate private-chat + trigger + unused-delivery check; given is committed only if the text actually appears in the final block. Admin diagnostics use dry_run and do not consume one-time delivery state.

## Observability

The returned info includes mode, candidate count, gate outcome, disclosure levels, fallback mode, final_ids, dropped_ids, and Source-fallback counters. Normal logs should contain only counts and IDs, never Source text or private assembled content.

## Explicit interfaces and side effects

`recall/domain.py` explicitly exports supported queries, retrieval/assembly entries and the context-injection writer; `recall/ports.py` reuses existing app repository/cache/retriever protocols. Legacy imports remain valid. `query_block()` and `RecallService.query()` are pure memory queries: cache/Source/version reads and derived in-memory indexing are allowed, but no memory commit or given-state update occurs. Preview uses the pure query.

`record_context()` / `RecallService.record_context_injection()` are explicit writes. They mark designated memories only when their body occurs in the final block and their IDs survived assembly. The meaning remains **body included in model context**, independent of later model or send success. AstrBot calls recording after attaching the block to the request. Deferred/proactive runtime calls the optional generic `MemoryContextRecorder` immediately before model invocation; Runtime has no designated-domain rules.

Legacy `build_block()` and `RecallService.build()` retain their parameters, return shapes and default query-plus-recording behavior; `dry_run=True` stays read-only. This compatibility side effect must be considered when adding new callers. Runtime context construction uses the pure service query.

| Files | Responsibility / effects | Logical complexity and coupling |
|---|---|---|
| `pipeline.py` | Candidate → scoring/filtering → disclosure → assembly; compatible write wrapper | Medium/high: coordinates existing rules, no duplicated query implementation |
| `selection.py` | Config interpretation, speaker identity and recent-memory fallback | Low: pure rules, subject affinity is a ranking signal |
| `source_fallback.py` | Bounded evidence reads → current Artifact discovery | Medium: reads only, no raw Source body injected |
| `disclosure.py` | Apply shared privacy decisions and safe wording overrides | Medium: one disclosure stage before rendering |
| `context_recording.py`, `designated.py` | Explicit context inclusion records and existing private/trigger guards | Medium: versioned writes separate from queries |
| `retriever.py`, `bm25.py`, `seed.py`, `tokenizer.py`, `spread.py` | Derived lexical/graph signals, index invalidation and bounded expansion | Medium: no model/network calls or business writes |
| `score.py`, `gate.py`, `intent.py`, `temporal.py` | Existing scoring, evidence, intent and date rules | Medium: formulas, thresholds and time behavior unchanged |
| `assemble.py`, `history.py`, `drift.py`, `scope.py` | Narrative budget, optional impression history, spontaneous recall and explicit candidate access | Medium: caller supplies candidates/resources |

`tests/test_recall_context_integration.py` covers pure reads, compatible default writes, explicit repeated recording, budget-dropped bodies and model/send failure timing. `tests/test_recall_interface_contract.py` covers the approved export set and optional generic runtime capability; fresh import-order tests cover top-level and plugin namespaces. Existing privacy, scope and frozen BM25 acceptance remain required; these tests are not live-model quality evidence.
