"""开口策略的 AstrBot 胶水层（临时接线，等 #116 宿主适配落地后删除）。

职责只有三件：
1. 把宿主事件映射成 RuntimeInput；
2. 调 AttentionPolicy 得到 RunDecision；
3. 按结论放行 / stop_event，并注入场景提示。

额度状态复用运行时 SessionState（键为 ``umo#sender``），不新增表。
"""

from __future__ import annotations

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

from ..app.runtime.attention import AttentionPolicy, thresholds_from_config
from ..app.runtime.contracts import SessionState, WakeAction
from ..app.runtime.scene_hints import compose, time_window
from ..app.runtime.signals import Signals
from .astrbot_event import to_runtime_input

QUOTA_TTL = 900.0
MAX_MEMORY_SCAN = 150


def _bigrams(text: str) -> set[str]:
    """字符二元组，足够做轻量相关度，不引入依赖。"""
    raw = "".join(ch for ch in str(text or "") if ch.isalnum())
    return {raw[i : i + 2] for i in range(len(raw) - 1)}


class AttentionHooks:
    """AstrBot 侧的策略胶水；不持有存储，全部走已有服务。"""

    # ---------------- 配置 ----------------
    def _attention_enabled(self) -> bool:
        try:
            return bool(self._c("attention_policy_enabled", True))
        except Exception:  # noqa: BLE001
            return False

    def _scene_hints_enabled(self) -> bool:
        try:
            return bool(self._c("scene_hints_enabled", True))
        except Exception:  # noqa: BLE001
            return False

    def _address_names(self) -> tuple[str, ...]:
        """可被叫的名字；配置逗号分隔，默认大肥鱼。"""
        try:
            raw = str(self._c("attention_address_names", "大肥鱼,肥鱼") or "")
        except Exception:  # noqa: BLE001
            raw = "大肥鱼,肥鱼"
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    def _owner_id(self) -> str:
        try:
            umo = str(getattr(self, "owner_umo", "") or "")
            return umo.split(":")[-1] if umo else ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------------- 信号 ----------------
    def _relationship(self, speaker: str) -> float:
        """关于这个说话人的印象条数 → 0..1（6 条封顶）。"""
        try:
            count = 0
            for art in self.cache.active("memory"):
                if str(art.payload.get("level") or "") != "impression":
                    continue
                if speaker in (str(art.header.said_by or ""), str(art.header.subject_id or "")):
                    count += 1
            return min(1.0, count / 6.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _relevance(self, text: str) -> float:
        """消息与已有记忆的字符重合度 → 0..1（轻量、不调模型）。"""
        query = _bigrams(text)
        if not query:
            return 0.0
        best = 0.0
        try:
            arts = self.cache.active("memory")[:MAX_MEMORY_SCAN]
        except Exception:  # noqa: BLE001
            return 0.0
        for art in arts:
            body = str(art.payload.get("text") or "")
            if not body:
                continue
            overlap = len(query & _bigrams(body)) / len(query)
            if overlap > best:
                best = overlap
                if best >= 1.0:
                    break
        return min(1.0, best)

    def _heat(self, session_id: str) -> float:
        """最近 5 分钟该会话的缓冲条数 → 0..1（10 条封顶）。"""
        try:
            cutoff = time.time() - 300
            recent = 0
            for turn in self.buffer.items:
                if str(turn.session_id) != session_id:
                    continue
                stamp = getattr(turn, "at", "")
                try:
                    recent += 1 if not stamp or float(stamp) >= cutoff else 0
                except (TypeError, ValueError):
                    recent += 1
            return min(1.0, recent / 10.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def _signals(self, mapped, state: SessionState) -> Signals:
        now = time.time()
        return Signals(
            relationship=self._relationship(mapped.speaker_id),
            relevance=self._relevance(mapped.text),
            heat=self._heat(mapped.session_id),
            recency=max(0.0, now - float(state.last_seen_at or 0.0)),
            window=time_window(time.localtime().tm_hour),
        )

    # ---------------- 额度 ----------------
    def _quota_for(self, signals: Signals, policy: AttentionPolicy) -> int:
        """auto 模式按关系给额度；off/fixed 由配置覆盖。"""
        mode = str(self._c("stranger_quota_mode", "auto") or "auto")
        if mode == "off":
            return 0
        if mode.startswith("fixed:"):
            try:
                return max(0, int(mode.split(":", 1)[1]))
            except (TypeError, ValueError):
                return policy.stranger_quota(signals)
        return policy.stranger_quota(signals)

    def _gate_quota(
        self, mapped, event: AstrMessageEvent, decision, signals, policy
    ) -> bool:
        """返回是否放行；额度按 (会话, 说话人) 复用 SessionState。"""
        if decision.action is WakeAction.REPLY and (
            mapped.private or mapped.is_owner
        ):
            return True
        if decision.action is WakeAction.REPLY and (mapped.mentioned or mapped.addressed):
            # 被点名（@ 或叫名字）一律放行；额度只影响之后不点名的续聊
            self._save_quota(mapped, max(0, self._quota_for(signals, policy)))
            return True
        if decision.action is WakeAction.REPLY:
            state = self.services.runtime.store.get(self._quota_key(mapped))
            remaining = int(state.unread_count or 0)
            if remaining <= 0:
                return False
            self._save_quota(mapped, remaining - 1)
            return True
        return False

    def _quota_key(self, mapped) -> str:
        return f"{mapped.session_id}#{mapped.speaker_id}"

    def _save_quota(self, mapped, remaining: int) -> None:
        try:
            store = self.services.runtime.store
            key = self._quota_key(mapped)
            state = store.get(key)
            state.unread_count = int(remaining)
            state.last_seen_at = time.time()
            store.put(state)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[seekmemory] 额度记录失败：{type(exc).__name__}")

    # ---------------- 钩子 ----------------
    async def attention_gate(self, event: AstrMessageEvent) -> None:
        """在 AstrBot 唤醒之后、回复之前决定放行或停住。"""
        if not self.ready or not self._attention_enabled() or self.services is None:
            return
        if not self._may_observe(event):
            return
        try:
            mapped = to_runtime_input(
                event,
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                owner_id=self._owner_id(),
                names=self._address_names(),
            )
            if not mapped.text:
                return
            store = self.services.runtime.store
            state = store.get(mapped.session_id)
            signals = self._signals(mapped, state)
            policy = AttentionPolicy(thresholds_from_config(self._c))
            decision = policy.decide(mapped, state, signals, time.time())
            allowed = self._gate_quota(mapped, event, decision, signals, policy)
            state.last_action = decision.action.value
            state.last_reason = decision.reason
            store.put(state)
            self.journal.record(
                "attention",
                "reply" if allowed else "stop",
                decision.reason,
                context={
                    "scene": mapped.scene,
                    "role": mapped.role,
                    "relationship": round(signals.relationship, 2),
                    "relevance": round(signals.relevance, 2),
                },
            )
            if not allowed:
                event.stop_event()
        except Exception as exc:  # noqa: BLE001 - 策略失败不影响正常聊天
            logger.warning(f"[seekmemory] 开口策略失败（放行）：{type(exc).__name__}")

    async def inject_scene_hints(self, event: AstrMessageEvent, req) -> None:
        """把时间/身份/亲疏提示追加到系统提示，替代 persona_gate 的提示部分。"""
        if not self._scene_hints_enabled() or self.services is None:
            return
        try:
            mapped = to_runtime_input(
                event,
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                owner_id=self._owner_id(),
                names=self._address_names(),
            )
            state = self.services.runtime.store.get(mapped.session_id)
            text = compose(mapped, self._signals(mapped, state), time.localtime().tm_hour)
            if text:
                req.system_prompt = (req.system_prompt or "") + "\n\n【场景】" + text + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[seekmemory] 场景提示失败：{type(exc).__name__}")
