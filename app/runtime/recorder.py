"""Single write-back service for completed runtime runs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Protocol
from uuid import uuid4

try:
    from ...core.source import Source, make_source_id
except ImportError:  # top-level package import in scripts/tests
    from core.source import Source, make_source_id
from .episode import EpisodeRecord, normalize_tool_calls, safe_error_code

if TYPE_CHECKING:
    from ..ports import ArtifactCache


class SourceSink(Protocol):
    def append_sources(self, sources: list[Source]) -> int: ...


class PendingSink(Protocol):
    def add(self, umo: str, text: str, sender: str = "", source_id: str = "",
            at: str = "", *, source: Source | None = None, turn_id: str = "",
            reply_to: str = "", deferred: bool = False,
            role: str = "user") -> Any: ...


class CheckpointSink(Protocol):
    def record(self, art: Any, at: str = "") -> bool: ...


class EpisodeWriter(Protocol):
    def record(self, episode: EpisodeRecord) -> None: ...


@dataclass(frozen=True)
class RecordedTurn:
    source_id: str
    turn_id: str
    topic_id: str = ""


@dataclass(frozen=True)
class RecordedReply:
    run_id: str
    session_id: str
    turn_id: str
    assistant_source_id: str
    response_chars: int


@dataclass
class _SourceWriteback:
    """Completed stages for one immutable Source / 一条不可变原始消息的已完成写回阶段。"""

    source: Source = field(repr=False)
    deferred: bool = False
    recall_ids: tuple[str, ...] = ()
    source_done: bool = False
    projection_done: bool = False
    topic_id: str = ""
    reinforced: set[str] = field(default_factory=set)


class RunRecorder:
    """Owns assistant Source, pending buffer and episode write-back.

    A run id is the idempotency boundary. Source ids are deterministic and the
    database uses INSERT OR IGNORE, while repeated calls in one process are
    short-circuited here so checkpoints and episode rows are not duplicated.
    """

    def __init__(
        self,
        *,
        sources: SourceSink | None,
        buffer: PendingSink | None,
        checkpoint: CheckpointSink | None,
        episodes: EpisodeWriter | None,
        cache: ArtifactCache | None = None,
        clock=None,
    ) -> None:
        self.sources = sources
        self.buffer = buffer
        self.checkpoint = checkpoint
        self.episodes = episodes
        self.cache = cache
        self.clock = clock or (lambda: datetime.datetime.now().isoformat(timespec="seconds"))
        self._turns: dict[str, RecordedTurn] = {}
        self._replies: dict[str, RecordedReply] = {}
        self._episodes: set[str] = set()
        self._pending_turns: dict[str, _SourceWriteback] = {}
        self._pending_replies: dict[str, _SourceWriteback] = {}
        self._pending_episodes: dict[str, EpisodeRecord] = {}

    @staticmethod
    def new_run_id() -> str:
        return uuid4().hex

    def record_user(
        self,
        *,
        session_id: str,
        text: str,
        speaker_id: str,
        event_id: str = "",
        at: str = "",
        deferred: bool = False,
    ) -> RecordedTurn:
        """Write one user Source and its extraction projection exactly once."""
        clean = str(text or "").strip()
        if not clean:
            raise ValueError("user message text is empty")
        session = str(session_id or "")
        speaker = str(speaker_id or "")
        moment = str(at or self.clock())
        source_id = make_source_id(
            event_id=str(event_id or ""),
            session_id=session,
            speaker_id=speaker,
            role="user",
            text=clean,
            at=moment,
        )
        turn_id = str(event_id or source_id)
        key = turn_id
        existing = self._turns.get(key)
        if existing is not None:
            return existing

        source = Source(
            source_id,
            turn_id,
            session,
            speaker,
            "user",
            clean,
            moment,
        )
        progress = self._pending_turns.setdefault(key, _SourceWriteback(source, deferred))
        return self._finish_user(key, progress)

    def record_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        turn_id: str = "",
        reply_to: str = "",
        at: str = "",
        recall_ids: Iterable[str] = (),
        source_suffix: str = "assistant",
    ) -> RecordedReply:
        """Write one assistant Source and its pending projection exactly once."""
        key = str(run_id or "").strip() or self.new_run_id()
        existing = self._replies.get(key)
        if existing is not None:
            return existing

        clean = str(text or "").strip()
        if not clean:
            raise ValueError("assistant reply text is empty")
        session = str(session_id or "")
        speaker = str(speaker_id or "")
        moment = str(at or self.clock())
        turn = str(turn_id or "").strip()
        if not turn:
            turn = make_source_id(
                session_id=session,
                speaker_id=speaker,
                role="assistant",
                text=clean,
                at=moment,
            )
        source_id = make_source_id(
            event_id=f"{turn}:{source_suffix or 'assistant'}",
            session_id=session,
            speaker_id=speaker,
            role="assistant",
            text=clean,
        )
        source = Source(
            source_id,
            turn,
            session,
            speaker,
            "assistant",
            clean,
            moment,
            reply_to=str(reply_to or "") or None,
        )
        progress = self._pending_replies.setdefault(
            key, _SourceWriteback(source, recall_ids=tuple(dict.fromkeys(recall_ids or ()))),
        )
        return self._finish_reply(key, progress)

    def record_delivery(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str = "reply",
        response_chars: int = 0,
        tool_calls: Iterable[Any] | None = (),
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
    ) -> None:
        """Record a successful platform delivery once for this run."""
        self._record_episode(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action=action,
            delivered=True,
            response_chars=response_chars,
            tool_calls=tool_calls,
            outcome="ok",
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
            at=at,
        )

    def record_error(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str = "reply",
        error: Any = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
    ) -> None:
        """Record one failed run without message bodies or exception text."""
        self._record_episode(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action=action,
            delivered=False,
            error=safe_error_code(error) or "error",
            outcome="error",
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
            at=at,
        )

    def record_deferred_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        user_source_id: str,
        decision: str = "wait",
        reason: str = "deferred_wait",
        at: str = "",
    ) -> RecordedReply:
        """Persist a deferred assistant reply and its delivered episode."""
        reply = self.record_reply(
            run_id=run_id,
            session_id=session_id,
            text=text,
            speaker_id=speaker_id,
            turn_id=user_source_id,
            reply_to=user_source_id,
            at=at,
            source_suffix="deferred",
        )
        self.record_delivery(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action="reply",
            response_chars=reply.response_chars,
            user_source_id=user_source_id,
            assistant_source_id=reply.assistant_source_id,
            at=at,
        )
        return reply

    def record_deferred_error(
        self,
        *,
        run_id: str,
        session_id: str,
        user_source_id: str,
        error: Any,
        decision: str = "wait",
        reason: str = "deferred_wait",
        at: str = "",
    ) -> None:
        self.record_error(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            action="reply",
            error=error,
            user_source_id=user_source_id,
            at=at,
        )

    def _record_episode(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        action: str,
        delivered: bool,
        response_chars: int = 0,
        tool_calls: Iterable[Any] | None = (),
        outcome: str = "",
        error: str = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
        at: str = "",
    ) -> None:
        key = str(run_id or "").strip()
        if key and key in self._episodes:
            return
        if self.episodes is None:
            return
        episode = EpisodeRecord(
            session_id=str(session_id or ""),
            at=str(at or self.clock()),
            decision=str(decision or ""),
            reason=str(reason or ""),
            action=str(action or ""),
            delivered=bool(delivered),
            response_chars=max(0, int(response_chars or 0)),
            tool_calls=normalize_tool_calls(tool_calls),
            outcome=str(outcome or ""),
            error=str(error or ""),
            user_source_id=str(user_source_id or ""),
            assistant_source_id=str(assistant_source_id or ""),
            run_id=key,
        )
        pending_key = key or self.new_run_id()
        episode = self._pending_episodes.setdefault(pending_key, episode)
        self.episodes.record(episode)
        self._pending_episodes.pop(pending_key, None)
        if key:
            self._episodes.add(key)

    def _write_source(self, progress: _SourceWriteback) -> None:
        """Resume only unfinished evidence and queue stages / 仅续写未完成的证据及队列阶段。"""
        source = progress.source
        if not progress.source_done:
            if self.sources is not None:
                self.sources.append_sources([source])
            progress.source_done = True
        if not progress.projection_done:
            if self.buffer is not None:
                kwargs = dict(source=source, turn_id=source.turn_id)
                if source.role == "assistant":
                    kwargs["role"] = "assistant"
                else:
                    kwargs["deferred"] = progress.deferred
                turn = self.buffer.add(source.session_id, source.text, source.speaker_id,
                                       source.id, source.at, **kwargs)
                progress.topic_id = str(getattr(turn, "topic_id", "") or "")
            progress.projection_done = True

    def _finish_user(self, key: str, progress: _SourceWriteback) -> RecordedTurn:
        """Complete and release a user write-back / 完成并释放用户消息写回。"""
        self._write_source(progress)
        result = RecordedTurn(progress.source.id, progress.source.turn_id, progress.topic_id)
        self._turns[key] = result
        self._pending_turns.pop(key, None)
        return result

    def _finish_reply(self, key: str, progress: _SourceWriteback) -> RecordedReply:
        """Complete reply stages, retaining successful reinforcement IDs / 完成回复阶段，保留已完成强化编号。"""
        self._write_source(progress)
        if self.checkpoint is not None:
            for art_id in progress.recall_ids:
                if art_id in progress.reinforced:
                    continue
                art = self.cache.get(str(art_id)) if self.cache is not None else None
                if art is not None and getattr(art.header, "family", "") == "memory":
                    self.checkpoint.record(art, at=progress.source.at)
                progress.reinforced.add(art_id)
        source = progress.source
        result = RecordedReply(key, source.session_id, source.turn_id, source.id, len(source.text))
        self._replies[key] = result
        self._pending_replies.pop(key, None)
        return result

    def retry_pending(self) -> int:
        """Retry writes without generation or sending; return completed items.

        只补写，不生成或发送；返回完成项数。失败项保留到下一轮。
        """
        completed = 0
        for pending, finish in ((self._pending_turns, self._finish_user),
                                (self._pending_replies, self._finish_reply)):
            for key, progress in list(pending.items()):
                try:
                    finish(key, progress)
                    completed += 1
                except Exception:
                    continue
        if self.episodes is not None:
            for key, episode in list(self._pending_episodes.items()):
                try:
                    self.episodes.record(episode)
                except Exception:
                    continue
                self._pending_episodes.pop(key, None)
                if episode.run_id:
                    self._episodes.add(episode.run_id)
                completed += 1
        return completed
