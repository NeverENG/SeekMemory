"""将经过认证的管理请求适配到 AstrBot 桥接接口。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

from .service import ManagementService

if TYPE_CHECKING:
    from ..main import Main


class WebRoutes:
    """管理当前插件实例注册的路由。"""

    def __init__(self, plugin: Main) -> None:
        self.plugin = plugin

    def register(self) -> None:
        """宿主支持插件 Web API 时，注册原生接口处理器。"""
        try:
            import astrbot.api.web  # noqa: F401
        except ImportError:
            self.plugin.journal.record("webui", "warning", "宿主不支持插件 Web API")
            return
        self.plugin.context.register_web_api(
            "/astrbot_plugin_seekmemory/manage/<action>",
            self.handle,
            ["GET", "POST"],
            "SeekMemory 记忆管理",
        )

    def close(self) -> None:
        """仅移除仍由当前实例持有的路由，保留后续实例的替代路由。"""
        routes = self.plugin.context.registered_web_apis
        routes[:] = [route for route in routes if route[1] != self.handle]

    async def _status(self) -> dict:
        """汇总引擎、模型、任务与配置状态，不发送模型请求。

        Returns:
            状态接口的数据；模型查询失败仅影响对应检查项。
        """
        from ..store.ledger import Ledger

        plugin = self.plugin

        checks = [
            {"name": "engine", "ok": plugin.ready, "detail": "记忆引擎"},
            {
                "name": "journal",
                "ok": not plugin.journal.persistence_error,
                "detail": "生命周期日志持久化",
            },
        ]
        if plugin.db is not None:
            checks.append(
                {
                    "name": "ledger",
                    "ok": Ledger(plugin.db).verify(),
                    "detail": "账本哈希链",
                }
            )
        try:
            provider = await plugin.context.get_using_provider_async()
            provider_detail = "检查模型服务配置，未发送模型请求"
        except Exception as exc:
            provider = None
            provider_detail = f"查询模型服务失败： {type(exc).__name__}"
        checks.append(
            {
                "name": "provider",
                "ok": provider is not None,
                "detail": provider_detail,
            }
        )
        pending = (
            Counter(turn.session_id for turn in plugin.buffer.items)
            if plugin.buffer is not None
            else Counter()
        )
        topics = []
        if plugin.buffer is not None:
            for session, topic_id, turns in plugin.buffer.topics():
                timestamps = []
                for turn in turns:
                    try:
                        timestamps.append(datetime.fromisoformat(turn.at).astimezone())
                    except (TypeError, ValueError):
                        continue
                topics.append(
                    {
                        "id": topic_id,
                        "session": session,
                        "count": len(turns),
                        "oldestAt": min(timestamps).isoformat() if timestamps else None,
                    }
                )
        active = plugin.jobs.task is not None and not plugin.jobs.task.done()
        return {
            "ready": plugin.ready,
            "checks": checks,
            "activeTask": {
                "id": plugin.jobs.task_id,
                "kind": plugin.jobs.kind,
            }
            if active
            else None,
            "pending": [
                {"session": key, "count": value} for key, value in pending.items()
            ],
            "pendingTopics": topics,
            "extractionPolicy": {
                "backlogThreshold": plugin._c("backlog_flush_at", 30),
                "topicTtlSeconds": plugin._c("topic_ttl_seconds", 86400.0),
                "maxTopicsPerBatch": max(1, plugin._c("max_sessions_per_flush", 6)),
            },
            "checkpointPending": plugin.checkpoint.pending()
            if plugin.checkpoint
            else None,
            "schedulerCount": sum(not task.done() for task in plugin._schedulers),
            "config": {
                key: plugin.cfg.get(key)
                for key in (
                    "owner_umo",
                    "open_to",
                    "observe_groups",
                    "summary_time",
                    "weekly_day",
                    "idle_flush_seconds",
                    "checkpoint_seconds",
                    "max_sessions_per_flush",
                    "budget_chars",
                    "recall_k",
                    "trusted",
                    "explore_rate",
                    "recall_min_ev_abs",
                    "recall_min_ev_rel",
                    "min_pending",
                    "backlog_flush_at",
                    "topic_ttl_seconds",
                    "max_flushes_per_day",
                    "enable_reflect",
                    "max_episodes",
                )
            },
        }

    async def handle(self, action: str):
        """分发经过认证的管理操作。

        Args:
            action: 明确支持的管理接口操作。

        Returns:
            宿主原生 JSON 响应，包含有界诊断信息或错误。
        """
        from astrbot.api.web import error_response, json_response, request

        plugin = self.plugin
        if not request.username:
            return error_response("需要管理员登录", status_code=401)
        read_actions = {"status", "records", "detail", "events"}
        write_actions = {"update", "diagnose", "task", "cancel"}
        if action not in read_actions | write_actions:
            return error_response("未知操作", status_code=404)
        if request.method != ("GET" if action in read_actions else "POST"):
            return error_response("请求方法不支持", status_code=405)
        try:
            if action == "events":
                kind = request.query.get("kind", "")
                status = request.query.get("status", "")
                search = request.query.get("search", "").casefold()
                events = [
                    row
                    for row in reversed(plugin.journal.events)
                    if (not kind or row["kind"] == kind)
                    and (not status or row["status"] == status)
                    and (
                        not search
                        or search in (row["message"] + row["taskId"]).casefold()
                    )
                ]
                return json_response({"events": events, "capacity": 500})
            if action == "status":
                return json_response(await self._status())
            if (
                not plugin.ready
                or plugin.db is None
                or plugin.cache is None
                or plugin.graph is None
            ):
                return error_response(
                    "记忆引擎不可用，请检查运行检测与日志", status_code=503
                )
            service = ManagementService(
                plugin.db, plugin.cache, plugin.graph, plugin._c,
                plugin.hybrid_retriever,
            )
            if action == "records":
                return json_response({"records": service.catalog()})
            if action == "detail":
                return json_response(service.detail(request.query.get("id", "")))
            if len(await request.body()) > 65536:
                return error_response("请求内容过大", status_code=413)
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("请求体必须为 JSON 对象")
            if action == "diagnose":
                with plugin.journal.span("diagnose", "recall.preview") as metrics:
                    result = service.diagnose(body)
                    metrics.update(
                        visible=len(result["visible"]),
                        excluded=len(result["excluded"]),
                        chars=len(result["block"]),
                    )
                return json_response(result)
            if action == "update":
                if plugin.jobs.task is not None and not plugin.jobs.task.done():
                    return error_response("维护任务运行中，请稍后编辑", status_code=409)
                with plugin.journal.span("edit", "artifact.revise") as metrics:
                    node_id = service.update(body)
                    metrics.update(
                        artifactId=node_id, revision=body["expectedRevision"] + 1
                    )
                return json_response({"id": node_id})
            if body.get("confirmed") is not True:
                raise ValueError("请先确认操作")
            if action == "cancel":
                if (
                    body.get("id") != plugin.jobs.task_id
                    or plugin.jobs.task is None
                    or plugin.jobs.task.done()
                ):
                    return error_response("任务已结束或不存在", status_code=409)
                plugin.jobs.task.cancel()
                return json_response({"id": plugin.jobs.task_id})
            kind = body.get("kind")
            if not isinstance(kind, str) or kind not in {"extract", "weekly"}:
                raise ValueError("未知任务类型")
            operation = plugin._nightly if kind == "extract" else plugin._weekly
            return json_response({"id": plugin.jobs.submit(kind, operation)})
        except LookupError:
            return error_response("记忆不存在，请刷新列表", status_code=404)
        except ValueError as exc:
            if str(exc) == "revision_conflict":
                return error_response(
                    "记忆已被修改，请重新加载后再保存", status_code=409
                )
            return error_response(f"校验失败：{exc}", status_code=400)
        except RuntimeError:
            return error_response("任务正在运行或插件正在停止", status_code=409)
        except Exception as exc:
            plugin.journal.record(
                "webui",
                "failed",
                "管理请求失败",
                error=exc,
                context={"action": action},
            )
            return error_response("操作失败，请查看插件日志", status_code=500)
