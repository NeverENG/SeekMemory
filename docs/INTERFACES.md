# Public Interfaces

This page is for contributors who want to extend SeekMemory without reading the whole codebase. It describes the stable extension points, their contracts and the tests that protect them.

## Design rules

- Source is the only immutable truth.
- Artifact is a derived, versioned interpretation.
- Production writes go through ArtifactStore.commit with expected_revision.
- SQL lives only in store/db.py.
- Retrievers do not write.
- ChatModel is stateless. Context management belongs to the caller.

## Protocols in app/ports.py

### ChatModel

    async def complete(request: ChatRequest) -> ChatResponse

A provider adapter converts a provider-neutral request into one model call. It does not keep conversation state. ProviderChatModel is the built-in adapter.

### Retriever

    def retrieve(query: str, pool: list[Artifact]) -> list[RetrievalCandidate]

A retriever may score, rank or merge lexical and graph signals. It must only use the supplied visible pool. It must not write, call a model or query the database in a loop. GraphRetriever and HybridRetriever are built-in implementations.

### SourceStore

    def append_sources(sources: list[Source]) -> int

Append immutable Source rows. Repeating the same source id is idempotent.

### ArtifactStore

    def commit(art, *, expected_revision, op, reason="", source_ids=(), state_events=()) -> None
    def get(node_id: str) -> Artifact | None

commit writes the new head, append-only version, evidence, ledger and optional state events atomically. expected_revision is required. A stale writer must fail with VersionError. SQL must not be added outside store/db.py.

### StateStore

    def append_state_event(event: StateEvent) -> None
    def history(node_id: str) -> list[dict]

State events and history support reinforcement and audit. Production revisions should commit their state event together with the Artifact through ArtifactStore.commit.

## Shared DTOs in app/contracts.py

- DialogueTurn: one buffered turn; session_id, speaker_id, role and text are required.
- ChatRequest: provider-neutral request. max_tokens defaults to 800; temperature defaults to 0.0.
- ChatResponse: provider-neutral response with text required and usage fields optional.
- WriteOutcome: extraction result; distinguishes written, skipped, errors and model_failed.
- RecallRequest and RecallResult: boundary DTOs for callers that should not import the recall pipeline.
- RetrievalCandidate: Artifact plus activation and lexical scores. lexical is normalized to 0..1.

## Adding an interface or implementation

1. Open an issue for the interface change.
2. Add the protocol or DTO with a short docstring.
3. Add it to tests/test_public_interfaces.py.
4. Add one minimal built-in implementation.
5. Run the full test suite.

## Tests

    python3 -m unittest tests.test_public_interfaces -v
    python3 -m unittest discover -s tests -p 'test_*.py' -q

The contract tests check built-in implementations against runtime-checkable protocols and lock required DTO fields and defaults.

## Scope

This is the first contribution layer. It does not yet cover a plugin marketplace, third-party adapter certification or a public benchmark leaderboard.
