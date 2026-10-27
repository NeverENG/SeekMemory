"""将经过认证的管理请求适配到 AstrBot 桥接接口。"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import Main


class WebRoutes:
    """管理当前插件实例注册的路由。"""

    def __init__(self, plugin: Main) -> None:
        self.plugin = plugin
        self._import_start_lock = asyncio.Lock()

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

    @staticmethod
    def _role_selection(body: dict):
        from ..services.import_policy import RoleSelection

        values = {}
        for key in (
            "botPlatformId",
            "targetPlatformId",
            "targetUmo",
            "botMemberId",
            "targetMemberId",
        ):
            value = body.get(key, "")
            if not isinstance(value, str):
                raise ValueError(f"{key} 必须是字符串")
            values[key] = value.strip()
        if len(values["botPlatformId"]) > 256 or len(values["targetPlatformId"]) > 256:
            raise ValueError("平台账号 ID 过长")
        return RoleSelection(
            bot_platform_id=values["botPlatformId"],
            target_platform_id=values["targetPlatformId"],
            target_umo=values["targetUmo"],
            bot_member_id=values["botMemberId"],
            target_member_id=values["targetMemberId"],
        )

    def _jobs_busy(self) -> bool:
        jobs = self.plugin.jobs
        return bool(jobs is not None and jobs.task is not None and not jobs.task.done())

    @staticmethod
    def _import_task_payload(task: dict) -> dict:
        return {
            "id": task["id"],
            "status": task["status"],
            "formatId": task["format_id"],
            "sourceCount": task["source_count"],
            "duplicateCount": task["duplicate_count"],
            "skippedCount": task["skipped_count"],
            "pendingCount": task["pending_count"],
            "extractedCount": task["extracted_count"],
            "failedCount": task["failed_count"],
            "errorTypes": task["error_types"],
            "personaStatus": task["persona_status"],
            "canRetry": bool(task.get("can_retry", False)),
            "createdAt": task["created_at"],
            "updatedAt": task["updated_at"],
            "terminalAt": task["terminal_at"],
        }

    def _submit_import(self, task_id: str, selection) -> None:
        plugin = self.plugin
        if plugin.jobs is None or plugin.services is None:
            raise RuntimeError("任务执行器不可用")

        async def operation() -> None:
            plugin.active_import_started_task_id = task_id
            await plugin.services.import_service.run(task_id, selection)

        plugin.jobs.submit(
            "history_import",
            operation,
        )
        plugin.active_import_task_id = task_id

        def clear_active(_task) -> None:
            if getattr(plugin, "active_import_task_id", "") == task_id:
                plugin.active_import_task_id = ""
                plugin.active_import_started_task_id = ""

        if plugin.jobs.task is not None:
            plugin.jobs.task.add_done_callback(clear_active)

    async def _status(self) -> dict:
        """汇总引擎、模型、任务与配置状态，不发送模型请求。

        Returns:
            状态接口的数据；模型查询失败仅影响对应检查项。
        """
        plugin = self.plugin

        checks = [
            {"name": "engine", "ok": plugin.ready, "detail": "记忆引擎"},
            {
                "name": "journal",
                "ok": not plugin.journal.persistence_error,
                "detail": "生命周期日志持久化",
            },
        ]
        if plugin.store is not None:
            checks.append(
                {
                    "name": "ledger",
                    "ok": plugin.services.status_service.ledger_valid(),
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
            "capacity": plugin.services.capacity_service.status(),
            "persona": plugin.services.status_service.persona(),
            "dream": plugin.dream.status() if getattr(plugin, "dream", None) else None,
            "budget": plugin.budget.as_dict() if getattr(plugin, "budget", None) else None,
            "checkpointPending": plugin.checkpoint.pending()
            if plugin.checkpoint
            else None,
            "schedulerCount": sum(not task.done() for task in plugin.services.background_service.tasks),
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
        read_actions = {
            "status", "records", "detail", "events", "traces",
            "importTasks", "importTask",
        }
        write_actions = {
            "update", "rollbackPersona", "diagnose", "task", "cancel",
            "importUpload", "importValidate", "importConfirm", "importCancel",
            "importRetry", "importAbandon",
        }
        if action not in read_actions | write_actions:
            return error_response("未知操作", status_code=404)
        if request.method != ("GET" if action in read_actions else "POST"):
            return error_response("请求方法不支持", status_code=405)
        try:
            if action == "traces":
                return json_response(plugin.run_traces.snapshot(request.query.get("state", "all")))
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
                or plugin.store is None
                or plugin.cache is None
                or plugin.graph is None
            ):
                return error_response(
                    "记忆引擎不可用，请检查运行检测与日志", status_code=503
                )
            service = plugin.services.management_service
            import_service = getattr(plugin.services, "import_service", None)
            if action.startswith("import") and import_service is None:
                return error_response("历史导入暂不可用", status_code=503)
            if action == "importUpload":
                file_store = getattr(plugin, "import_files", None)
                if file_store is None:
                    return error_response("历史导入暂不可用", status_code=503)
                files = await request.files()
                upload = files.get("file") if hasattr(files, "get") else None
                if upload is None:
                    return error_response("请选择 ChatLab JSON 或 JSONL 文件", status_code=400)
                import_service.cleanup()
                staged = await file_store.save_upload(upload)
                preview = await import_service.inspect_upload(staged.key)
                return json_response(
                    {
                        "stageKey": staged.key,
                        "filename": staged.filename,
                        "size": staged.size,
                        "preview": preview,
                    }
                )
            if action == "importTasks":
                return json_response(
                    {"tasks": [self._import_task_payload(task) for task in import_service.tasks()]}
                )
            if action == "importTask":
                task = import_service.task(request.query.get("id", ""))
                if task is None:
                    return error_response("导入任务不存在", status_code=404)
                return json_response({"task": self._import_task_payload(task)})
            if action == "records":
                return json_response({"records": service.catalog()})
            if action == "detail":
                return json_response(service.detail(request.query.get("id", "")))
            if action != "importUpload" and len(await request.body()) > 65536:
                return error_response("请求内容过大", status_code=413)
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("请求体必须为 JSON 对象")
            if action == "importValidate":
                selection = self._role_selection(body)
                result = await import_service.validate_stage(
                    str(body.get("stageKey") or ""), selection
                )
                return json_response({"preview": result})
            if action == "importConfirm":
                if body.get("confirmed") is not True:
                    raise ValueError("请先确认导入结果")
                selection = self._role_selection(body)
                async with self._import_start_lock:
                    if self._jobs_busy():
                        return error_response("另一个维护任务正在运行，请稍后导入", status_code=409)
                    task_id = import_service.create_task(
                        str(body.get("stageKey") or ""), selection
                    )
                    try:
                        self._submit_import(task_id, selection)
                    except RuntimeError:
                        import_service.imports.finish_task(
                            task_id, "failed", persona_status="not_run", retain_stage=True
                        )
                        raise
                    return json_response({"id": task_id})
            if action == "importCancel":
                task_id = str(body.get("id") or "")
                if (
                    body.get("confirmed") is not True
                    or plugin.jobs is None
                    or getattr(plugin, "active_import_task_id", "") != task_id
                    or plugin.jobs.kind != "history_import"
                    or plugin.jobs.task is None
                    or plugin.jobs.task.done()
                ):
                    return error_response("导入任务已结束或不存在", status_code=409)
                task_started = (
                    getattr(plugin, "active_import_started_task_id", "") == task_id
                )
                task_stage = import_service.imports.task_stage(task_id)
                plugin.jobs.task.cancel()
                if not task_started:
                    stage_key = str((task_stage or {}).get("stage_key") or "")
                    import_service.imports.finish_task(
                        task_id, "cancelled", persona_status="not_run"
                    )
                    if stage_key:
                        import_service.files.delete(stage_key)
                return json_response({"id": task_id})
            if action == "importRetry":
                if body.get("confirmed") is not True:
                    raise ValueError("请先确认重新导入")
                async with self._import_start_lock:
                    if self._jobs_busy():
                        return error_response("另一个维护任务正在运行，请稍后重试", status_code=409)
                    task_id, selection = await import_service.retry_task(
                        str(body.get("id") or "")
                    )
                    try:
                        self._submit_import(task_id, selection)
                    except RuntimeError:
                        import_service.imports.finish_task(
                            task_id, "failed", persona_status="not_run", retain_stage=True
                        )
                        raise
                    return json_response({"id": task_id})
            if action == "importAbandon":
                if body.get("confirmed") is not True:
                    raise ValueError("请先确认放弃任务")
                task_id = str(body.get("id") or "")
                if getattr(plugin, "active_import_task_id", "") == task_id:
                    return error_response("任务运行中，请先取消", status_code=409)
                if not import_service.abandon(task_id):
                    return error_response("该任务当前不能放弃", status_code=409)
                return json_response({"id": task_id})
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
            if action == "rollbackPersona":
                if plugin.jobs.task is not None and not plugin.jobs.task.done():
                    return error_response("维护任务运行中，请稍后回滚", status_code=409)
                with plugin.journal.span("edit", "persona.rollback") as metrics:
                    result = service.rollback_persona(body)
                    metrics.update(
                        artifactId=result["id"], revision=result["revision"],
                        restoredRevision=result["restoredRevision"],
                    )
                return json_response(result)
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
            operation = plugin.services.background_service.nightly if kind == "extract" else plugin.services.background_service.weekly
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
