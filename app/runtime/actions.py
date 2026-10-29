"""Content-free action execution and audit orchestration; host and repository are injected.

不含正文的动作执行及审计编排，宿主和仓储由外部注入。
"""

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
    """Hash session/run/action/callback identity; reject an empty callback key / 散列会话、运行、动作及回调标识，拒绝空回调编号。"""
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
    """Build content-free attempts and terminal records; the sink enforces persistence / 构造不含正文的尝试及终态记录，由外部存储保证落库。"""

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
        """Persist an attempted action before execution with a stable identity / 执行前以稳定编号保存动作尝试。"""
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
        """Persist a terminal transition from an attempted action / 从尝试状态保存终态迁移。"""
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
    """Map audit to an injected repository; own no SQL or connection / 将审计映射到注入仓储，不拥有 SQL 或连接。"""

    def __init__(self, repository: ActionRepository) -> None:
        self.repository = repository

    def append(self, record: ActionRecord) -> None:
        """Persist one action transition; repository failures propagate / 保存一次动作迁移，仓储失败向上抛出。"""
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
    """Execute through one host port; isolate optional audit failures / 通过唯一宿主端口执行，隔离可选审计失败。"""

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
        """Try to persist an attempt; audit failure returns None / 尝试保存动作开始记录，审计失败返回空。"""
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
        except Exception:  # noqa: BLE001 - audit failure is isolated / 隔离审计失败
            return None

    def finish(
        self,
        attempted,
        status: ActionStatus,
        *,
        at: float | None = None,
        reason: str = "",
    ) -> None:
        """Try to record terminal status without changing execution outcome / 尝试记录终态，不改变执行结果。"""
        if self.ledger is None or attempted is None:
            return
        try:
            self.ledger.finish(attempted, status, at=self._at(at), reason=reason)
        except Exception:  # noqa: BLE001 - audit failure is isolated / 隔离审计失败
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
        """Record attempt, execute, then record terminal; sanitize host failures / 记录尝试、执行、记录终态，并规整宿主错误。"""
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
        except Exception:  # noqa: BLE001 - sanitize host failures / 宿主失败不泄漏正文
            result = ActionResult(False, "host_action_failed")
        status = ActionStatus.SUCCEEDED if result.ok else ActionStatus.FAILED
        self.finish(attempted, status, at=at, reason=result.reason)
        return result


class ActionMessageSender:
    """Expose legacy text sending over ActionPort without another ledger / 以动作端口提供旧文本发送能力，不另建账本。"""

    def __init__(self, port) -> None:
        self.port = port

    async def send(self, session_id: str, text: str) -> bool:
        """Execute SEND_TEXT and return observed success / 执行 SEND_TEXT 并返回观察到的成功状态。"""
        from .contracts import ActionKind, ActionRequest

        result = await self.port.execute(
            ActionRequest(session_id=session_id, kind=ActionKind.SEND_TEXT, text=text)
        )
        return bool(result.ok)
