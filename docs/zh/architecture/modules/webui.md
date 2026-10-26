# WebUI：管理 API 与控制台

## 分层

- webui/routes.py 注册 AstrBot 插件管理路由，做请求认证、方法/请求体限制、状态码映射和服务调用。
- services/management_service.py 实现框架无关的目录、详情、编辑、人格 bootstrap/rollback 和召回诊断用例。
- dashboard/ 是 React/TypeScript 管理界面，按 memory library、control/diagnostics/logs/run-traces/persona evidence 等工作区组织状态与视图。
- AstrBot 页面桥接器把已认证的宿主请求送到插件 API；静态页面和 mock 模式不连接真实数据库。

## 管理写入

管理详情可显示 Artifact 原文、版本快照、版本级来源证据和账本数据。编辑请求必须带读取时的 expectedRevision、确认标记、允许修改的 payload/scope/state 和原因；后端 family 校验后走 ArtifactStore.commit，revision 冲突返回冲突状态。WebUI 不直接写 SQL 或 Cache。

Persona 回滚从历史版本取内容，在同一稳定 ID 上创建新 revision，不删除历史。已 merged 的普通 Artifact 不能独立恢复。维护任务运行时，编辑和回滚会被拒绝，避免并行修改同一状态。

## 诊断与可观测性

召回诊断复用 RecallService，并以 dry_run 跳过 designated 的 given 写入；不会调用模型或改变记忆。Status 的 provider 检查只确认配置，不发送模型请求。

Jobs 将手动与定时任务限制为单个活动任务。Journal 保存有界业务阶段记录和异常类型/源码位置；Agent Run Trace 另由 TraceStore 保存字段白名单时间线；容量 Trace 又是单独的进程内环形样本。三者用途不同，均不应存消息正文、模型响应或工具参数/结果。

根目录 openapi.yaml 是管理 API 契约源；dashboard/src/contracts/generated.ts 由类型生成命令维护，Zod 继续验证运行时输入。详情见[管理界面操作指南](../../guides/webui.md)和[控制台开发说明](../../guides/development.md)。
