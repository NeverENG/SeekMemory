# app: Ports, DTOs, and Application Policies

## Responsibility

app defines shared data shapes, replaceable ports, and lightweight pure policies. It lets business code depend on interfaces rather than SQLite, AstrBot providers, or frontend transport objects.

## Boundary objects

- DialogueTurn is a buffered view with session, speaker, role, text, time, Source/turn/topic IDs, and reply relation.
- ExtractionState describes the queue status for a Source; it does not duplicate message text.
- ChatRequest / ChatResponse are provider-neutral model-call shapes; usage and latency metadata are optional.
- WriteOutcome summarizes writes, skips, errors, retryability, and token usage.
- RecallRequest / RecallResult provide a narrower recall-call boundary.

app/ports.py defines ChatModel, Retriever, SourceStore, ArtifactStore, ArtifactCache, ExtractionStore, LedgerStore, and MetricsStore. ArtifactStore.commit requires expected_revision; commit_many is for version writes that must succeed atomically as a group. The ports describe behavior but do not implement I/O.

## Policies and use-case helpers

- **budget.py** centralizes request-side limits for system text, memory injection, group context, and history, and provides a character-to-token estimate. The estimate is for budgets and observation, not an exact tokenizer count.
- **flush_policy.py** decides when extraction is due, selects topic batches round-robin across sessions, chunks oversized topics, and keeps a user turn with its reply where possible. A topic batch stays within one session.
- **checkpoint.py** accepts only Artifacts retained in the final context. It combines repeated hits inside a cooldown and later commits reinforcement with an Artifact revision and StateEvent.
- **dream.py** coordinates at most one recoverable daily extraction/maintenance cycle, including batch, call/token budgets, usage summary, and Dream ledger. Concrete extraction and maintenance are injected.
- **persona_synthesis.py** bounds persona synthesis input and parses model drafts. It does not write storage, select evidence, or decide whether a revision is eligible.
- **app/runtime/** defines host-agnostic AgentRuntime policies and ports; see [Agent Runtime](runtime.md).

## Ownership of side effects

ChatModel is a stateless call port. app budget, flush, wake, and timing policies do not connect to a database or schedule host tasks. Application services call ports and choose transaction timing; store persists data; adapters provide host implementations.

Code entry points: [ports.py](../../../../app/ports.py), [contracts.py](../../../../app/contracts.py), [budget.py](../../../../app/budget.py).
