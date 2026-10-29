"""Runtime episode recording."""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .tools import ToolCall
from .contracts.ports import EpisodeRepository


_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$")


@dataclass(frozen=True)
class EpisodeRecord:
    session_id: str
    at: str
    decision: str
    reason: str
    action: str
    delivered: bool
    response_chars: int = 0
    tool_calls: tuple[str, ...] = ()
    outcome: str = ""
    error: str = ""
    user_source_id: str = ""
    assistant_source_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class EpisodeOutcome:
    """Safe outcome metadata for one runtime episode row."""

    outcome: str
    error: str = ""
    delivered: bool = True
    tool_calls: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.outcome == "ok"

    def fields(self) -> dict[str, Any]:
        """Return episode columns without message-body or argument values."""

        return {
            "delivered": self.delivered,
            "tool_calls": self.tool_calls,
            "outcome": self.outcome,
            "error": self.error,
        }


def safe_error_code(error: Any) -> str:
    """Reduce an exception/value to a bounded, body-free error code.

    Exception messages can contain user text, prompts, tool arguments or
    credentials. Only the exception class name is retained for exceptions.
    String values are retained only when they already look like a stable code.
    """

    if error is None:
        return ""
    if isinstance(error, BaseException):
        code = type(error).__name__
    else:
        code = str(error or "").strip()
    return code if _SAFE_ERROR_CODE.fullmatch(code) else "error"


def normalize_tool_calls(tool_calls: Iterable[str | ToolCall] | None) -> tuple[str, ...]:
    """Return tool names only; never persist arguments or result content."""

    if not tool_calls:
        return ()
    names: list[str] = []
    for item in tool_calls:
        if isinstance(item, ToolCall):
            value = item.name
        else:
            value = getattr(item, "name", item)
        name = str(value or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def episode_outcome(
    *,
    delivered: bool,
    tool_calls: Iterable[str | ToolCall] | None = (),
    tool_failed: bool = False,
    error: Any = None,
) -> EpisodeOutcome:
    """Classify one episode using metadata only.

    Delivery failure takes precedence over tool failure because it describes
    whether the user actually received the reply. Generic errors still preserve
    a stable error code without storing the exception message.
    """

    calls = normalize_tool_calls(tool_calls)
    code = safe_error_code(error)
    if not delivered:
        return EpisodeOutcome(
            outcome="delivery_failed",
            error=code or "delivery_failed",
            delivered=False,
            tool_calls=calls,
        )
    if tool_failed:
        return EpisodeOutcome(
            outcome="tool_error", error=code or "tool_error",
            delivered=True, tool_calls=calls,
        )
    if code:
        return EpisodeOutcome(
            outcome="error", error=code, delivered=True, tool_calls=calls
        )
    return EpisodeOutcome(outcome="ok", delivered=True, tool_calls=calls)


def delivery_failure_outcome(error: Any = None) -> EpisodeOutcome:
    """Build safe episode metadata for a known delivery failure."""

    return EpisodeOutcome(
        outcome="delivery_failed",
        error=safe_error_code(error) or "delivery_failed",
        delivered=False,
    )


def delivery_failure_metadata(error: Any = None) -> dict[str, Any]:
    """Return episode-field metadata for a delivery failure."""

    return delivery_failure_outcome(error).fields()


class EpisodeSink(Protocol):
    def append(self, episode: EpisodeRecord) -> None: ...


class EpisodeRecorder:
    def __init__(self, sink: EpisodeSink) -> None:
        self.sink = sink

    def record(self, episode: EpisodeRecord) -> None:
        self.sink.append(episode)


class JsonlEpisodeStore:
    """Append-only local episode log; never stores message bodies."""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.last_error = ""

    def append(self, episode: EpisodeRecord) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = asdict(episode)
                payload["tool_calls"] = list(normalize_tool_calls(episode.tool_calls))
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False,
                                            sort_keys=True) + "\n")
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001 - episode logging is fail-open
                self.last_error = type(exc).__name__


class RepoEpisodeStore:
    """Persist runtime episodes through the project's runtime repository."""

    def __init__(self, repository: EpisodeRepository) -> None:
        self.repository = repository
        self.last_error = ""

    def append(self, episode: EpisodeRecord) -> None:
        payload = asdict(episode)
        payload["id"] = f"ep_{uuid.uuid4().hex}"
        payload["tool_calls"] = list(normalize_tool_calls(episode.tool_calls))
        try:
            self.repository.append(payload)
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - episode logging is fail-open
            self.last_error = type(exc).__name__
