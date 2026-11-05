"""Compose real loopback runtime ingress with existing capture and disclosed recall.

将真实本机运行时入口接到既有捕获及已披露的召回，不另写记忆。
"""

from __future__ import annotations

import datetime
import math
import time
from typing import Callable

from app.runtime import AgentRuntime, InMemoryStateStore
from adapters.host_gateway import HostGateway, HostRequest


def _event_at(value: float) -> str:
    """Match DSH's Date(eventTime * 1000).toISOString for legacy Source timestamps.

    匹配旧 DSH 消息捕获时的毫秒级 UTC 时间格式。
    """
    try:
        seconds = float(value or 0.0)
        if not math.isfinite(seconds) or seconds <= 0:
            return ""
        # JavaScript Date truncates sub-millisecond precision before formatting.
        millis = math.trunc(seconds * 1000)
        return (datetime.datetime.fromtimestamp(millis / 1000, datetime.timezone.utc)
                .isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


class RuntimeIngress:
    """Accept DSH runtime events without replacing Source/Buffer or disclosure owners.

    接收 DSH 运行时事件，不取代 Source/Buffer 写入及披露的原所有者。
    """

    def __init__(self, *, owner: str, capture: Callable[[dict], tuple[int, dict]],
                 recall: Callable[[dict], tuple[int, dict]]) -> None:
        self.owner = owner
        self.capture = capture
        self.recall = recall
        # The live memory store remains authoritative; runtime decision state is process-local.
        self.runtime = AgentRuntime(InMemoryStateStore(), clock=time.time)

    def _allowed(self, body: dict) -> bool:
        return not body.get("subject_key") or str(body["subject_key"]) == self.owner

    def event(self, body: dict) -> tuple[int, dict]:
        """Capture evidence once, then let AgentRuntime observe the accepted input.

        原路径接纳证据后，由 AgentRuntime 观察已接纳输入。
        """
        if not isinstance(body, dict):
            return 400, {"error": "bad_request"}
        if not self._allowed(body):
            return 403, {"error": "subject_mismatch"}
        kind = str(body.get("kind") or "")
        if kind == "accept_user":
            try:
                event = HostGateway.project(HostRequest(**dict(body.get("input") or {})))
                if not event.session_id or not event.text.strip():
                    return 400, {"error": "invalid_runtime_input"}
                event_id = str(body.get("event_id") or event.event_id or "")
            except (TypeError, ValueError, OverflowError):
                return 400, {"error": "invalid_runtime_input"}
            status, saved = self.capture({
                "subject_key": self.owner, "session": event.session_id, "role": "user",
                "text": event.text, "msg_id": event_id, "at": _event_at(event.event_time),
            })
            if status != 200:
                return status, saved
            receipt = self.runtime.accept_user(event, event_id=event_id, now=time.time())
            return 200, {
                "decision": {
                    "action": receipt.decision.action.value,
                    "reason": receipt.decision.reason,
                    "attention": receipt.decision.attention.value,
                    "must_reply": receipt.decision.must_reply,
                },
                "source_id": saved["source_id"],
                "turn_id": event_id or saved["source_id"],
                "read_through_seq": receipt.read_through_seq,
            }
        if kind == "record_reply":
            text = body.get("text")
            at = body.get("at") or ""
            if not isinstance(text, str) or not text.strip() or not isinstance(at, str):
                return 400, {"error": "invalid_runtime_reply"}
            status, saved = self.capture({
                "subject_key": self.owner, "session": str(body.get("session_id") or ""),
                "role": "assistant", "speaker": "assistant", "text": text,
                "msg_id": str(body.get("turn_id") or ""), "at": at,
                "reply_to": str(body.get("reply_to") or ""),
            })
            if status != 200:
                return status, saved
            return 200, {
                "run_id": str(body.get("run_id") or ""),
                "session_id": str(body.get("session_id") or ""),
                "turn_id": str(body.get("turn_id") or saved["source_id"]),
                "assistant_source_id": saved["source_id"], "response_chars": len(text),
            }
        if kind == "record_delivery":
            self.runtime.record_delivery(
                run_id=str(body.get("run_id") or ""), session_id=str(body.get("session_id") or ""),
                decision=str(body.get("decision") or "reply"),
                reason=str(body.get("reason") or "delivered"),
                response_chars=int(body.get("response_chars") or 0),
                tool_calls=tuple(body.get("tool_calls") or ()),
                user_source_id=str(body.get("user_source_id") or ""),
                assistant_source_id=str(body.get("assistant_source_id") or ""),
                read_through_seq=body.get("read_through_seq"), now=time.time(),
            )
            return 200, {"accepted": True}
        if kind == "record_error":
            self.runtime.record_error(
                run_id=str(body.get("run_id") or ""), session_id=str(body.get("session_id") or ""),
                decision=str(body.get("decision") or "reply"), reason=str(body.get("reason") or "error"),
                error=str(body.get("error") or "host_error"),
                user_source_id=str(body.get("user_source_id") or ""),
                assistant_source_id=str(body.get("assistant_source_id") or ""),
            )
            return 200, {"accepted": True}
        if kind == "action_result":
            return 200, {"accepted": True}
        return 400, {"error": "unsupported_event"}

    def context(self, body: dict) -> tuple[int, dict]:
        """Adapt the runtime transport to the existing disclosure and budget owner.

        复用已有召回披露与预算，不另起记忆规则。
        """
        if not isinstance(body, dict):
            return 400, {"error": "bad_request"}
        if not self._allowed(body):
            return 403, {"error": "subject_mismatch"}
        status, result = self.recall({
            "subject_key": self.owner,
            "query": str(body.get("query") or body.get("value") or ""),
            "speaker": str(body.get("speaker_id") or ""),
            "private": bool(body.get("private")),
            "budget_chars": body.get("budget_chars"),
            "k": body.get("k"),
        })
        if status != 200:
            return status, result
        return 200, {"text": result["block"], "info": result["info"]}
