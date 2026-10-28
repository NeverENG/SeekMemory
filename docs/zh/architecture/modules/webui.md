# WebUI：管理 API 与控制台

## 分层

- `webui/` 只保留宿主无关的 jobs、journal 和 trace；AstrBot 管理路由位于 `adapters/astrbot/web.py`，由适配层负责认证、方法和状态码映射。
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

## 人格控制台读模型（GitHub #82 / #83）

以下路由复用已认证的 WebRoutes 边界，以 OpenAPI 为契约源，生产页面通过 Zod 校验响应。

| 操作 | 有界输出或命令 |
|---|---|
| `GET manage/graph` | 最近更新的 1,000 个 Artifact、最多 2,000 条真实或派生关联；不返回 Source 正文，遮蔽 secret/designated/shadow 内容 |
| `GET manage/impressions?offset=0` | 按主体与范围分组的最近 100 张印象卡片；不跨隐私边界合并身份 |
| `GET manage/dream` | 最近 100 次运行，仅保留白名单指标；缺失分诊指标为 null，不伪造为零 |
| `GET manage/packs?collection=official&offset=0` | 24 个人格文件摘要；mine 仅读取插件数据目录 |
| `GET manage/pack?reference=official/big_fish` | 已校验的规范人格文件，最多 64 KiB |
| `POST manage/persona` | 必须显式确认的 install、import 或可恢复的 remove；维护任务运行时均拒绝 |

人格包详情包含规范化 seed 的 SHA-256 digest。安装必须带 expectedId、expectedRevision 和 expectedDigest；预览内容改变时，在写入前返回 409。校验后的 seed 交给既有 bootstrap 路径，不创建第二条人格写入路径。

导入只保存蓝图。覆盖已有本地包需要旧 expectedVersion，且新版本必须不同；保留旧文件备份。文件适配器原子发布完整文件，不写 Artifact、Source、账本，也不发起模型请求。官方包只读。

首页事件流复用 manage/traces，不新增消息正文端点。既有详情、编辑、诊断及任务契约保持不变。

控制台通过 `POST manage/rollbackPersona` 提交 `{id, revision, reason, confirmed}`；确认前比较当前与目标版本，成功后刷新状态。管理服务创建新 revision 并记入账本，保留历史。该路由纳入 OpenAPI 和生产客户端校验。

Dream 明确显示 budget.stopped 和 dream_enabled，避免把预算耗尽当作完整完成，或把关闭调度显示为运行中。


人格包图片经 `GET manage/packArtwork?reference=…` 的管理员鉴权返回有界 PNG base64；完整导出使用 `GET manage/packExport?reference=…`，不暴露数据目录。目录仅返回可选、无正文的 artworkRef，图片不塞进目录响应。`POST manage/persona` 新增 importPack 命令，沿用确认、维护任务互斥及 expectedVersion 更新保护；请求体上限为 3 MiB，其他管理写入仍为 64 KiB。设定、图片和许可证共同参与预览 digest，安装只把规范 seed 交给 bootstrap。新包外层格式见[人格种子指南](../../guides/persona-seed.md)。
