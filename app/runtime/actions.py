"""Content-free action audit lifecycle for tool and host actions."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace

from .contracts import ActionKind, ActionRecord, ActionSink, ActionStatus
from .contracts.ports import ActionRepository
from .episode import safe_error_code


def action_idempotency_key(
    run_id: str,
    callback_key: str,
    kind: ActionKind,
    *,
    session_id: str = "",
) -> str:
    """Derive a stable opaque key without persisting a host callback identifier."""
    callback = str(callback_key or "").strip()
    if not callback:
        raise ValueError("callback_key is required for action idempotency")
    action_kind = ActionKind(kind)
    material = "\0".join((
        str(session_id or ""),
        str(run_id or ""),
        action_kind.value,
        callback,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _moment(value: float) -> float:
    moment = float(value)
    if not math.isfinite(moment) or moment < 0.0:
        raise ValueError("action time must be finite and non-negative")
    return moment


class ActionLedger:
    """Record idempotent attempts and one terminal outcome through an ActionSink."""

    def __init__(self, sink: ActionSink) -> None:
        self.sink = sink

    def begin(
        self,
        *,
        session_id: str,
        run_id: str,
        callback_key: str,
        kind: ActionKind,
        at: float,
        attempt: int = 1,
        reason: str = "",
    ) -> ActionRecord:
        """Append one content-free attempt with a stable callback identity."""
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("session_id is required for action audit")
        action_kind = ActionKind(kind)
        count = int(attempt)
        if count < 1:
            raise ValueError("attempt must be positive")
        record = ActionRecord(
            action_id=action_idempotency_key(
                run_id,
                callback_key,
                action_kind,
                session_id=session,
            ),
            session_id=session,
            run_id=str(run_id or ""),
            kind=action_kind,
            status=ActionStatus.ATTEMPTED,
            reason=safe_error_code(reason),
            attempt=count,
            at=_moment(at),
        )
        self.sink.append(record)
        return record

    def finish(
        self,
        attempted: ActionRecord,
        status: ActionStatus,
        *,
        at: float,
        reason: str = "",
    ) -> ActionRecord:
        """Append a success, failure, or cancellation for an attempted action."""
        if attempted.status is not ActionStatus.ATTEMPTED:
            raise ValueError("only an attempted action can transition to terminal")
        terminal_status = ActionStatus(status)
        if terminal_status is ActionStatus.ATTEMPTED:
            raise ValueError("terminal status must be succeeded, failed, or cancelled")
        record = replace(
            attempted,
            status=terminal_status,
            reason=safe_error_code(reason),
            at=_moment(at),
        )
        self.sink.append(record)
        return record


class RepoActionSink:
    """Adapt the SQL-owned runtime episode repository to the ActionSink port."""

    def __init__(self, repository: ActionRepository) -> None:
        self.repository = repository

    def append(self, record: ActionRecord) -> None:
        self.repository.append_action({
            "action_id": record.action_id,
            "action_kind": record.kind.value,
            "action_status": record.status.value,
            "attempt": record.attempt,
            "at": record.at,
            "session_id": record.session_id,
            "run_id": record.run_id,
            "reason": record.reason,
        })


class ActionExecutor:
    """Single execution and audit coordinator for runtime actions.

    Runtime-initiated actions go through this class. Host-native callbacks may
    use ``begin``/``finish`` directly, but they must not maintain a parallel
    action ledger.
    """

    def __init__(self, port, ledger: ActionLedger | None = None, clock=None) -> None:
        self.port = port
        self.ledger = ledger
        self.clock = clock or (lambda: 0.0)

    def _at(self, at: float | None) -> float:
        return float(self.clock() if at is None else at)

    def begin(
        self,
        request,
        *,
        run_id: str,
        callback_key: str,
        at: float | None = None,
        attempt: int = 1,
        reason: str = "",
    ):
        if self.ledger is None:
            return None
        try:
            return self.ledger.begin(
                session_id=request.session_id,
                run_id=run_id,
                callback_key=callback_key,
                kind=request.kind,
                at=self._at(at),
                attempt=attempt,
                reason=reason,
            )
        except Exception:  # noqa: BLE001 - audit is fail-open
            return None

    def finish(
        self,
        attempted,
        status: ActionStatus,
        *,
        at: float | None = None,
        reason: str = "",
    ) -> None:
        if self.ledger is None or attempted is None:
            return
        try:
            self.ledger.finish(attempted, status, at=self._at(at), reason=reason)
        except Exception:  # noqa: BLE001 - audit is fail-open
            return

    async def execute(
        self,
        request,
        *,
        run_id: str,
        callback_key: str,
        at: float | None = None,
        attempt: int = 1,
    ):
        from .contracts import ActionResult

        attempted = self.begin(
            request,
            run_id=run_id,
            callback_key=callback_key,
            at=at,
            attempt=attempt,
        )
        try:
            result = await self.port.execute(request)
        except Exception:  # noqa: BLE001 - host errors must not leak payloads
            result = ActionResult(False, "host_action_failed")
        status = ActionStatus.SUCCEEDED if result.ok else ActionStatus.FAILED
        self.finish(attempted, status, at=at, reason=result.reason)
        return result


class ActionMessageSender:
    """Compatibility SEND_TEXT view over the one ActionPort."""

    def __init__(self, port) -> None:
        self.port = port

    async def send(self, session_id: str, text: str) -> bool:
        from .contracts import ActionKind, ActionRequest

        result = await self.port.execute(
            ActionRequest(session_id=session_id, kind=ActionKind.SEND_TEXT, text=text)
        )
        return bool(result.ok)
