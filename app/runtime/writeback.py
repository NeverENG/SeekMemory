"""Process-local delivery receipts and retryable write-back, with no model/send access.

进程内交付凭据及可重试写回；无法调用模型或发送，不新增持久化格式。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Literal

from . import transitions
from .contracts import RunResult, SessionState, SessionStateStore
from .recorder import RunRecorder


@dataclass
class DeliveryReceipt:
    """Confirmed delivery and unfinished stages; reply text never enters diagnostics.

    已确认交付及未完成阶段；回复正文不进入诊断，完成后释放。
    """

    run_id: str
    session_id: str
    moment: float
    mode: Literal["normal", "deferred", "proactive"]
    decision: str
    reason: str
    text: str = field(default="", repr=False)
    speaker_id: str = ""
    user_source_id: str = ""
    assistant_source_id: str = ""
    response_chars: int = 0
    tool_calls: tuple[str, ...] = ()
    claimed: SessionState | None = field(default=None, repr=False)
    read_through_seq: int | None = None
    state_done: bool = False
    recorder_done: bool = False

    def result(self, pending: bool) -> RunResult:
        """Keep delivery true even if writes are pending / 待补写时交付状态仍为真。"""
        return RunResult(self.run_id, self.session_id, True,
                         assistant_source_id=self.assistant_source_id,
                         response_chars=self.response_chars,
                         error="writeback_pending" if pending else "")


class DeliveryWritebacks:
    """Own receipts until state and recording finish; do not schedule a second loop.

    保存凭据直到状态及记录完成；不创建第二套调度循环。
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], DeliveryReceipt] = {}
        self._completed: dict[tuple[str, str], RunResult] = {}

    def remember(self, receipt: DeliveryReceipt) -> DeliveryReceipt:
        """Store the first confirmed delivery before fallible writes / 在可能失败的写入前保留首次交付。"""
        key = (receipt.session_id, receipt.run_id)
        return self._pending.setdefault(key, receipt)

    def completed(self, session_id: str, run_id: str) -> RunResult | None:
        """Read a completed run without retaining its body / 读取已完成结果，不保留正文。"""
        return self._completed.get((session_id, run_id)) if run_id else None

    def for_session(self, session_id: str) -> DeliveryReceipt | None:
        """Find unfinished delivery before another background send / 后台再次发送前查找未完成交付。"""
        return next((receipt for receipt in self._pending.values()
                     if receipt.session_id == session_id), None)

    def retry(self, store: SessionStateStore, recorder: RunRecorder | None,
              session_id: str | None = None) -> int:
        """Retry unfinished stages only; return the number of completed receipts.

        仅补写未完成阶段，返回完成的凭据数；错误保留到下次调用。
        """
        completed = 0
        for key, receipt in list(self._pending.items()):
            if session_id is not None and receipt.session_id != session_id:
                continue
            try:
                self._finish(receipt, store, recorder)
            except Exception:
                continue
            self._completed[key] = receipt.result(False)
            self._pending.pop(key, None)
            receipt.text = ""
            completed += 1
        return completed

    def _finish(self, receipt: DeliveryReceipt, store: SessionStateStore,
                recorder: RunRecorder | None) -> None:
        """Confirm bounded state first, then source/projection/audit / 先确认有界状态，再保存证据、投影和审计。"""
        if not receipt.state_done:
            state = store.get(receipt.session_id)
            if receipt.mode == "proactive":
                state = transitions.finish_proactive(
                    state, receipt.moment, receipt.reason, receipt.claimed,
                )
            else:
                state = transitions.mark_delivered(
                    state, receipt.moment, claimed=receipt.claimed,
                    read_through_seq=receipt.read_through_seq,
                )
            state.revision = max(0, int(state.revision or 0)) + 1
            store.put(state)
            receipt.state_done = True
        if recorder is not None and not receipt.recorder_done:
            at = datetime.datetime.fromtimestamp(
                receipt.moment, datetime.timezone.utc,
            ).isoformat(timespec="seconds")
            if receipt.mode == "normal":
                recorder.record_delivery(
                    run_id=receipt.run_id, session_id=receipt.session_id,
                    decision=receipt.decision, reason=receipt.reason,
                    response_chars=receipt.response_chars,
                    tool_calls=receipt.tool_calls, user_source_id=receipt.user_source_id,
                    assistant_source_id=receipt.assistant_source_id, at=at,
                )
            else:
                reply = recorder.record_deferred_reply(
                    run_id=receipt.run_id, session_id=receipt.session_id,
                    text=receipt.text, speaker_id=receipt.speaker_id,
                    user_source_id=receipt.user_source_id,
                    decision=receipt.decision, reason=receipt.reason, at=at,
                )
                receipt.assistant_source_id = reply.assistant_source_id
                receipt.response_chars = reply.response_chars
            receipt.recorder_done = True
