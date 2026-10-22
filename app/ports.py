from __future__ import annotations

from typing import Protocol, runtime_checkable

try:
    from ..core.artifact import Artifact
    from ..core.source import Source
    from ..core.versioning import StateEvent
    from ..core.retrieval import RetrievalCandidate
    from .contracts import ChatRequest, ChatResponse, ExtractionState
except ImportError:
    from core.artifact import Artifact
    from core.source import Source
    from core.versioning import StateEvent
    from core.retrieval import RetrievalCandidate
    from app.contracts import ChatRequest, ChatResponse, ExtractionState


@runtime_checkable
class ChatModel(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...


@runtime_checkable
class SourceStore(Protocol):
    def append_sources(self, sources: list[Source]) -> int: ...


@runtime_checkable
class ArtifactStore(Protocol):
    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple[StateEvent, ...] = ()) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...


@runtime_checkable
class StateStore(Protocol):
    def append_state_event(self, event: StateEvent) -> None: ...
    def history(self, node_id: str) -> list[dict]: ...


@runtime_checkable
class ExtractionStore(Protocol):
    def enqueue_extraction(
        self, source: Source, topic_id: str, created_at: str = ""
    ) -> bool: ...
    def put_extraction_state(self, state: ExtractionState) -> bool: ...
    def pending_extractions(self) -> list[dict]: ...
    def mark_extraction_succeeded(self, source_ids: list[str]) -> int: ...
    def mark_extraction_failed(self, source_ids: list[str], error_type: str) -> int: ...
