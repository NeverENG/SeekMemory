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

## Disclosure and delivery

core.disclosure combines context affinity, subject fit, scope prior, sensitivity, and relevance into full, paraphrase, hint, or silence. Lower than full uses fixed generic sentences, not the original text or tags. Being selected does not mean an item made the final block; injection does not prove that the model used it.

family=secret never enters the ordinary candidate pool. A memory with scope=shadow can only use a masked expression. family=designated has a separate private-chat + trigger + unused-delivery check; given is committed only if the text actually appears in the final block. Admin diagnostics use dry_run and do not consume one-time delivery state.

## Observability

The returned info includes mode, candidate count, gate outcome, disclosure levels, fallback mode, final_ids, dropped_ids, and Source-fallback counters. Normal logs should contain only counts and IDs, never Source text or private assembled content.
