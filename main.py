"""SeekMemory 插件入口。

只做三件事：
1. 把 AstrBot 的事件桥接给 core（不写业务逻辑）
2. 定时触发夜间抽取与每周整理
3. 全程 fail-open —— 记忆系统出任何问题都不能影响正常聊天
"""

from __future__ import annotations

import asyncio
import datetime
from functools import partial
from pathlib import Path

from astrbot.api import logger, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .app.checkpoint import CheckpointManager
from .app.contracts import DialogueTurn
from .app.flush_policy import decide_flush
from .core.capacity import (
    NORMAL,
    PROTECTIVE,
    SATURATED,
    CapacityDecision,
    CapacityGovernor,
    CapacitySnapshot,
    CapacityThresholds,
)
from .core.graph import Graph
from .core.source import Source, make_source_id
from .core.tree import Tree
from .perceive.absorb import absorb, worth_now
from .perceive.buffer import Buffer
from .perceive.calls import log_call
from .perceive.model import ProviderChatModel
from .recall.designated import is_private
from .recall.pipeline import build_block
from .recall.retriever import HybridRetriever
from .store.cache import Cache
from .store.db import DB
from .webui.jobs import Jobs
from .webui.journal import Journal
from .webui.routes import WebRoutes


class Main(star.Star):
    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.cfg = config or {}
        self.ready = False
        self.db: DB | None = None
        self.cache: Cache | None = None
        self.tree: Tree | None = None
        self.graph: Graph | None = None
        self.hybrid_retriever: HybridRetriever | None = None
        self.buffer: Buffer | None = None
        self.checkpoint: CheckpointManager | None = None
        self._flushing = False
        self._flush_day = ""
        self._flush_count = 0
        self._schedulers: list[asyncio.Task] = []
        self.data_path = (
            Path(str(self._c("db_path", ""))).expanduser()
            if self._c("db_path", "")
            else Path(get_astrbot_plugin_data_path()) / "seekmemory" / "memory.db"
        )
        self.journal = Journal(self.data_path.parent / "lifecycle.jsonl")
        self.jobs = Jobs(self.journal)
        artifact_limit = max(1, int(self._c("max_episodes", 500)))
        self.capacity = CapacityGovernor(
            CapacityThresholds(
                artifact_pressured_count=max(1, int(artifact_limit * 0.8)),
                artifact_saturated_count=artifact_limit,
            )
        )
        self._capacity_state = NORMAL
        self._capacity_action_mark = ""
        self._degrade_recall = False
        self._last_context_chars = 0
        self._init_engine()
        self.web = WebRoutes(self)
        self.web.register()

    # ---------------- 配置 ----------------
    def _c(self, key: str, default):
        try:
            v = self.cfg.get(key, default)
            if v is None:
                return default
            return type(default)(v)
        except Exception:
            return default

    @property
    def owner_umo(self) -> str:
        return str(self._c("owner_umo", ""))

    @property
    def trusted_ids(self) -> set[str]:
        raw = str(self._c("trusted", ""))
        return {x.strip() for x in raw.replace("，", ",").split(",") if x.strip()}

    # ---------------- 初始化 ----------------
    def _init_engine(self) -> None:
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self.db = DB(str(self.data_path))
            self.cache = Cache(self.db)
            self.cache.load()
            self.tree = Tree(self.db, self.cache)
            self.graph = Graph(self.db, self.cache)
            self.hybrid_retriever = HybridRetriever(self.graph, self.cache)
            self.buffer = Buffer(
                str(self.data_path.parent / "pending.json"), db=self.db
            )
            migrated = self.buffer.migrate_legacy()
            self.ready = True
            self.checkpoint = CheckpointManager(
                self.db, self.cache, int(self._c("checkpoint_seconds", 1800))
            )
            self.journal.record(
                "plugin", "ready", f"已加载 {self.cache.size()} 条有效记忆"
            )
            if migrated:
                self.journal.record(
                    "capacity",
                    "info",
                    "旧 pending 已迁移为 Source 投影",
                    context={"rows": migrated},
                )
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
            self.journal.record("plugin", "failed", "记忆引擎初始化失败", error=e)
            logger.error(f"[seekmemory] 初始化失败，记忆功能降级：{e}")

    # ---------------- 权限 ----------------
    def _may_remember(self, event: AstrMessageEvent) -> bool:
        """私聊侧的记忆权限（沿用 open_to 配置）。"""
        mode = str(self._c("open_to", "owner_only"))
        if mode == "everyone":
            return True
        umo = getattr(event, "unified_msg_origin", "")
        if umo == self.owner_umo:
            return True
        if mode == "owner_and_trusted":
            sid = str(event.get_sender_id())
            return sid in self.trusted_ids or umo == self.owner_umo
        return False

    def _group_chat(self, event: AstrMessageEvent) -> bool:
        """是不是群聊消息。"""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        return ":GroupMessage:" in umo

    def _may_observe(self, event: AstrMessageEvent) -> bool:
        """能不能把这句话记下来：私聊按 open_to，群聊按 observe_groups。"""
        if self._may_remember(event):
            return True
        return bool(self._c("observe_groups", True)) and self._group_chat(event)

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        """能不能给她注入记忆：主人私聊 + 观察中的群；别人的私聊不注入。"""
        return self._may_observe(event)

    # ---------------- 读路径：注入 ----------------
    @filter.on_llm_request()
    async def inject_memory(self, event: AstrMessageEvent, req) -> None:
        if not self.ready or self.cache is None:
            return
        try:
            if not self._may_recall(event):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            block, info = self._recall_block(
                text, umo, is_private(event), str(event.get_sender_id())
            )
            self._last_context_chars = len(block)
            log_call(self._calls_path(), umo, info)
            if self.checkpoint is not None:
                for art_id in info.get("picked_ids", ()):
                    art = self.cache.get(str(art_id))
                    if art is not None:
                        self.checkpoint.record(art)
            self.journal.record(
                "recall",
                "info",
                "召回文本已组装",
                stage="assemble",
                context={key: info[key] for key in ("mode", "picked", "chars")},
            )
            if block:
                req.system_prompt = (req.system_prompt or "") + "\n\n" + block + "\n"
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
        except Exception as e:  # noqa: BLE001
            self.journal.record("recall", "failed", "召回失败", error=e)
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{e}")

    def _calls_path(self) -> str:
        """调用日志路径：和数据目录放一起。"""
        return str(self.data_path.parent / "calls.jsonl")

    def _recall_block(
        self, text: str, umo: str = "", private: bool = False, speaker: str = ""
    ) -> tuple[str, dict]:
        """交给读路径模块：常驻层 + 检索 + 偶然浮现。"""
        conf = self._c
        if self._degrade_recall:
            def reduced(key: str, default):
                if key == "budget_chars":
                    return max(80, int(self._c(key, default) * 0.5))
                if key == "recall_k":
                    return max(1, int(self._c(key, default) * 0.5))
                return self._c(key, default)

            conf = reduced
        return build_block(
            self.cache,
            self.graph,
            self.db,
            umo,
            text,
            private,
            conf,
            self.owner_umo,
            speaker,
            log=lambda msg: logger.info(f"[seekmemory] {msg}"),
            hybrid_retriever=self.hybrid_retriever,
        )

    # ---------------- 写路径：缓冲 ----------------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_observe(event):
                return
            text = (event.message_str or "").strip()
            if not text or self.buffer is None:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            sender = str(event.get_sender_id())
            event_id = str(
                getattr(getattr(event, "message_obj", None), "message_id", "") or ""
            )
            now = datetime.datetime.now().isoformat(timespec="seconds")
            source_id = make_source_id(
                event_id=event_id,
                session_id=umo,
                speaker_id=sender,
                role="user",
                text=text,
                at=now,
            )
            turn_id = event_id or source_id
            source = Source(source_id, turn_id, umo, sender, "user", text, now)
            self.buffer.add(
                umo,
                text,
                sender,
                source_id,
                now,
                source=source,
                turn_id=turn_id,
            )
            event.set_extra("_seekmemory_turn_id", turn_id)
            event.set_extra("_seekmemory_source_id", source_id)
        except Exception:
            pass

    @filter.on_llm_response()
    async def capture_reply(self, event: AstrMessageEvent, response) -> None:
        try:
            if not self._may_observe(event) or self.db is None:
                return
            if str(getattr(response, "role", "assistant")) == "err":
                return
            text = str(getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            turn_id = str(event.get_extra("_seekmemory_turn_id", "") or "")
            if not turn_id:
                turn_id = make_source_id(
                    session_id=umo,
                    speaker_id=str(event.get_sender_id()),
                    role="assistant",
                    text=text,
                )
            source_id = make_source_id(
                event_id=f"{turn_id}:assistant",
                session_id=umo,
                speaker_id=str(event.get_self_id()),
                role="assistant",
                text=text,
            )
            now = datetime.datetime.now().isoformat(timespec="seconds")
            source = Source(
                source_id,
                turn_id,
                umo,
                str(event.get_self_id()),
                "assistant",
                text,
                now,
                reply_to=str(event.get_extra("_seekmemory_source_id", "") or ""),
            )
            self.db.append_sources([source])
        except Exception:
            pass

    @filter.on_astrbot_loaded()
    async def start_jobs(self) -> None:
        if not self.ready or self.jobs.closed or self._schedulers:
            return
        self._schedulers = [
            asyncio.create_task(operation())
            for operation in (
                self._nightly_loop,
                self._weekly_loop,
                self._idle_loop,
                self._checkpoint_loop,
            )
        ]
        self.journal.record("scheduler", "running", "维护定时任务已启动")

    async def initialize(self) -> None:
        """插件激活时启动定时任务，兼容热重载。"""
        await self.start_jobs()

    async def terminate(self) -> None:
        """依次取消本实例任务、移除路由并关闭存储。"""
        self.ready = False
        for task in self._schedulers:
            task.cancel()
        await asyncio.gather(*self._schedulers, return_exceptions=True)
        self._schedulers.clear()
        await self.jobs.close()
        self.web.close()
        if self.buffer is not None:
            self.buffer.save()
        if self.checkpoint is not None:
            self.checkpoint.flush()
        if self.db is not None:
            self.db.close()
            self.db = None
        self.journal.record("plugin", "stopped", "插件资源已释放")

    async def _checkpoint_loop(self) -> None:
        while True:
            interval = max(60, int(self._c("checkpoint_seconds", 1800)))
            await asyncio.sleep(interval)
            try:
                if self.checkpoint is not None:
                    self.checkpoint.flush()
            except Exception as e:
                logger.error(f"[seekmemory] checkpoint failed: {e}")

    async def _nightly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until(str(self._c("summary_time", "23:50")))
            )
            try:
                self.jobs.submit("nightly", self._nightly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 夜间整理失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    async def _weekly_loop(self) -> None:
        while True:
            await asyncio.sleep(
                self._seconds_until("23:55", weekday=self._c("weekly_day", 6))
            )
            try:
                self.jobs.submit("weekly", self._weekly)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 每周整理失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    @staticmethod
    def _seconds_until(hhmm: str, weekday: int | None = None) -> float:
        try:
            hh, mm = (int(x) for x in hhmm.split(":"))
            if not 0 <= hh <= 23 or not 0 <= mm <= 59:
                raise ValueError("定时时间无效")
        except Exception:
            hh, mm = 23, 50
        now = datetime.datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        if weekday is not None:
            weekday = int(weekday) % 7
            while target.weekday() != weekday:
                target += datetime.timedelta(days=1)
        return max((target - now).total_seconds(), 60)

    # ---------------- 抽取：空闲触发 + 夜间兜底 ----------------
    def _capacity_snapshot(self) -> CapacitySnapshot:
        """Collect bounded usage metrics without exposing row content."""
        usage = self.db.capacity_usage() if self.db is not None else {}
        trace_rows = len(self.journal.events)
        trace_age = 0.0
        if self.journal.events:
            try:
                oldest = datetime.datetime.fromisoformat(str(self.journal.events[0]["at"]))
                now = datetime.datetime.now(oldest.tzinfo)
                trace_age = max(0.0, now.timestamp() - oldest.timestamp())
            except (TypeError, ValueError):
                trace_age = 0.0
        return CapacitySnapshot(
            source_rows=int(usage.get("source_rows", 0)),
            source_bytes=int(usage.get("source_bytes", 0)),
            pending_rows=int(usage.get("pending_rows", 0)),
            pending_oldest_age_seconds=float(
                usage.get("pending_oldest_age_seconds", 0.0)
            ),
            artifact_count=int(usage.get("artifact_count", 0)),
            artifact_bytes=int(usage.get("artifact_bytes", 0)),
            expired_artifacts=int(usage.get("expired_artifacts", 0)),
            context_chars_per_turn=self._last_context_chars,
            trace_rows=trace_rows,
            trace_oldest_age_seconds=trace_age,
        )

    def _observe_capacity(self) -> CapacityDecision:
        """Evaluate and journal capacity transitions for scheduler decisions."""
        snapshot = self._capacity_snapshot()
        decision = self.capacity.evaluate(snapshot)
        self._degrade_recall = "degrade_recall" in decision.actions
        if decision.state != self._capacity_state:
            self.journal.record(
                "capacity",
                "warning" if decision.state != NORMAL else "info",
                f"容量状态切换为 {decision.state}",
                stage="governor",
                context={
                    "pending": snapshot.pending_rows,
                    "artifacts": snapshot.artifact_count,
                    "actions": len(decision.actions),
                },
            )
            if decision.state == PROTECTIVE:
                logger.warning("[seekmemory] 容量进入保护状态")
            self._capacity_state = decision.state
        return decision

    def _apply_capacity_maintenance(self, decision: CapacityDecision) -> None:
        """Execute non-queue lifecycle actions at most once per hour."""
        actionable = {
            "compact_artifacts",
            "forget_expired",
            "trim_trace",
            "alert",
        }
        if not actionable.intersection(decision.actions):
            return
        mark = datetime.datetime.now().strftime("%Y%m%d%H")
        if mark == self._capacity_action_mark:
            return
        self._capacity_action_mark = mark
        if "compact_artifacts" in decision.actions and self.db and self.cache:
            from .maintain.merge import merge_similar

            with self.journal.span("capacity", "compact_artifacts") as metrics:
                metrics["merged"] = merge_similar(
                    self.db,
                    self.cache,
                    threshold=0.6,
                    limit=50,
                )
        if "forget_expired" in decision.actions and self.db and self.cache:
            from .maintain.lifecycle import forget_expired

            with self.journal.span("capacity", "forget_expired") as metrics:
                metrics["forgotten"] = forget_expired(self.db, self.cache)
        if "trim_trace" in decision.actions:
            with self.journal.span("capacity", "trim_trace") as metrics:
                metrics["removed"] = self.journal.trim(400)
        if "alert" in decision.actions:
            self.journal.record(
                "capacity",
                "warning",
                "容量保护告警",
                stage="governor",
                context={"state": decision.state},
            )

    def _batch_cap(self, decision: CapacityDecision) -> int:
        cap = max(1, int(self._c("max_sessions_per_flush", 6)))
        return min(24, cap * 2) if "raise_batch_size" in decision.actions else cap

    def _should_flush(self, capacity: CapacityDecision | None = None) -> bool:
        if self._flushing or self.buffer is None or self.db is None:
            return False
        capacity = capacity or self._observe_capacity()
        today = datetime.date.today().isoformat()
        if self._flush_day != today:
            self._flush_day, self._flush_count = today, 0
        decision = decide_flush(
            pending=len(self.buffer.items),
            idle_seconds=self.buffer.idle_seconds(),
            worth_now=worth_now(self.buffer.items),
            flushes_today=self._flush_count,
            idle_flush_seconds=float(self._c("idle_flush_seconds", 0)),
            min_pending=int(self._c("min_pending", 8)),
            max_flushes_per_day=int(self._c("max_flushes_per_day", 2)),
            backlog_flush_at=int(self._c("backlog_flush_at", 30)),
            topic_age_seconds=self.buffer.oldest_topic_age(),
            topic_ttl_seconds=float(self._c("topic_ttl_seconds", 86400)),
        )
        if decision.should:
            return True
        return (
            capacity.state in (SATURATED, PROTECTIVE)
            and "schedule_extraction" in capacity.actions
        )

    async def _idle_loop(self) -> None:
        """聊完安静一会儿就抽，不用等到半夜。"""
        while True:
            await asyncio.sleep(30)
            try:
                capacity = self._observe_capacity()
                self._apply_capacity_maintenance(capacity)
                if self._should_flush(capacity):
                    self.jobs.submit("idle", lambda: self._flush("空闲"))
            except Exception as e:  # noqa: BLE001
                logger.error(f"[seekmemory] 空闲抽取失败：{e}")
                self.journal.record("scheduler", "failed", "定时任务提交失败", error=e)

    async def _nightly(self) -> None:
        """夜间兜底：把白天没来得及抽的尾巴抽掉。"""
        self._apply_capacity_maintenance(self._observe_capacity())
        await self._flush("夜间")

    def _split_topics(
        self, items: list[DialogueTurn], cap: int | None = None
    ) -> list[tuple[str, str, list[DialogueTurn]]]:
        """按上游话题归组与批次上限选择待抽取消息。"""
        buckets: dict[tuple[str, str], list[DialogueTurn]] = {}
        for turn in items:
            key = (str(turn.session_id or ""), str(turn.topic_id or ""))
            buckets.setdefault(key, []).append(turn)
        cap = int(cap or self._c("max_sessions_per_flush", 6))
        ordered = sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
        return [
            (session, topic, rows) for (session, topic), rows in ordered[: max(1, cap)]
        ]

    async def _flush(self, reason: str) -> None:
        """按上游会话与结果契约抽取，处理成功前保留缓冲。

        Args:
            reason: 触发本次抽取的业务原因。

        Raises:
            Exception: 批次结束后传播首个会话失败，供任务执行器记录失败状态。
        """
        if (
            self._flushing
            or self.buffer is None
            or not self.buffer.items
            or self.db is None
        ):
            return
        self._flushing = True
        try:
            capacity = self._observe_capacity()
            topics = self._split_topics(
                list(self.buffer.items), cap=self._batch_cap(capacity)
            )
            ready = []
            failure: Exception | None = None
            for umo, topic_id, part in topics:
                try:
                    with self.journal.span(
                        "extract", "provider.resolve", session=umo, topic=topic_id
                    ):
                        prov = await self.context.get_using_provider_async(umo or None)
                except Exception as exc:
                    if self.buffer is not None:
                        self.buffer.mark_failed(part, type(exc).__name__)
                    failure = failure or exc
                    continue
                if not prov:
                    self.journal.record(
                        "extract",
                        "warning",
                        "该会话尚未配置模型服务，保留待抽取消息",
                        stage="provider.resolve",
                        context={"session": umo, "topic": topic_id},
                    )
                    continue
                ready.append((umo, topic_id, part, prov))
            if not ready:
                if failure is not None:
                    raise failure
                return
            self._flush_count += 1
            written = 0
            for umo, topic_id, part, prov in ready:
                try:
                    with self.journal.span(
                        "extract",
                        "topic.extract",
                        session=umo,
                        topic=topic_id,
                        messages=len(part),
                    ) as metrics:
                        outcome = await absorb(
                            part,
                            self.db,
                            self.cache,
                            self.graph,
                            ProviderChatModel(prov),
                            log=partial(self.journal.record, "extract", "warning"),
                            owner_id=self.owner_umo.split(":")[-1]
                            if self.owner_umo
                            else "",
                            strict=True,
                            stage=partial(self.journal.span, "extract"),
                        )
                        metrics["written"] = outcome.written
                        metrics["skipped"] = outcome.skipped
                        if outcome.model_failed:
                            raise RuntimeError("模型抽取失败，保留待处理消息")
                except Exception as exc:
                    self.buffer.mark_failed(part, type(exc).__name__)
                    failure = failure or exc
                    continue
                # 成功后才推进投影状态；取消或模型失败不丢 Source。
                self.buffer.mark_succeeded(part)
                written += outcome.written
                logger.info(
                    f"[seekmemory] {reason}抽取 {umo or '未知会话'}："
                    f"话题 {topic_id}，{len(part)} 条对话，写入 {outcome.written} 条，跳过 {outcome.skipped} 条"
                )
            self.journal.record(
                "extract",
                "info",
                f"已尝试 {len(ready)} 个话题，写入 {written} 条记忆",
                context={"topics": len(ready), "written": written},
                stage="batch.complete",
            )
            if failure is not None:
                raise failure
        finally:
            self._flushing = False

    async def _weekly(self) -> None:
        from .maintain.decay import decay_all
        from .maintain.merge import merge_similar
        from .maintain.persona import distill_persona

        if self.db is None or self.cache is None:
            return
        today = datetime.date.today().isoformat()
        with self.journal.span("weekly", "decay") as metrics:
            dropped = decay_all(self.db, self.cache, today)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=0.6) as metrics:
            merged = merge_similar(self.db, self.cache, threshold=0.6)
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            persona = distill_persona(self.db, self.cache, today, self.owner_umo)
            metrics["updated"] = bool(persona)
        self.journal.record(
            "weekly",
            "info",
            f"遗忘 {dropped} 条，合并 {merged} 条，人格更新：{bool(persona)}",
            self.jobs.task_id,
        )
        logger.info(
            f"[seekmemory] 每周整理：遗忘 {dropped} 条，合并 {merged} 组，"
            f"人格 {'已更新' if persona else '无变化'}"
        )
