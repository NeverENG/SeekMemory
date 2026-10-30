# WebUI：管理 API 与控制台

## 分层

- `webui/` 保留宿主无关的 jobs、journal、trace 与 `console_api.py` 管理分发；独立 HTTP 边界位于 `adapters/console/`，AstrBot 管理路由位于 `adapters/astrbot/web.py`。
- services/management_service.py 实现框架无关的目录、详情、编辑、人格 bootstrap/rollback 和召回诊断用例。
- dashboard/ 是 React/TypeScript 管理界面，按 memory library、control/diagnostics/logs/run-traces/persona evidence 等工作区组织状态与视图。
- AstrBot 页面桥接器把已认证的宿主请求送到插件 API；独立页面通过可配置 HTTP API 和管理员令牌连接。Mock 模式仅操作内存。

## 独立 HTTP 边界

`scripts/console_http.py` 启动 `adapters/console/server.py`，`runtime.py` 组合既有 Store、Cache、RecallService、ManagementService、StatusService 和 PersonaPacks。生产调用通过应用用例读写，HTTP 分发不访问数据库，也不导入 AstrBot。HTTP 连接在线程间并行读写，完成请求解析后交给单个管理工作线程串行执行；SQLite 的创建、使用和关闭均位于该工作线程。空闲连接或尚未传完的请求体不占用数据库工作线程，关闭服务时先等待连接处理结束再关闭数据库。

`openapi.yaml` 使用 `/manage/<action>` 操作路径，服务器前缀分别为 `/api` 与 `/astrbot_plugin_seekmemory`。现有 AstrBot URL、请求体和错误结构保持兼容。独立 API 对所有读写操作校验 Bearer 令牌、Host 和来源；只允许本机监听与明确的开发 origin，限制请求大小，禁止缓存与重定向携带令牌。静态服务仅开放构建入口和 assets，不开放数据目录。

前端 `management-client.ts` 共享 Zod 响应校验；`http-client.ts` 与 `astrbot-client.ts` 分别实现 HTTP 和宿主桥接。组件只接收 ManagementClient。独立连接的令牌不进入 URL、日志或浏览器存储；断开会取消请求，401 返回连接页。状态中的可选 `capabilities.maintenanceTasks=false` 明确禁止独立服务未启动的后台任务；旧宿主未提供此字段时维持既有行为。

## 管理写入

管理详情可显示 Artifact 原文、版本快照、版本级来源证据和账本数据。编辑请求必须带读取时的 expectedRevision、确认标记、允许修改的 payload/scope/state 和原因；后端 family 校验后走 ArtifactStore.commit，revision 冲突返回冲突状态。WebUI 不直接写 SQL 或 Cache。

Persona 回滚从历史版本取内容，在同一稳定 ID 上创建新 revision，不删除历史。已 merged 的普通 Artifact 不能独立恢复。维护任务运行时，编辑和回滚会被拒绝，避免并行修改同一状态。

## 诊断与可观测性

召回诊断复用 RecallService，并以 dry_run 跳过 designated 的 given 写入；不会调用模型或改变记忆。Status 的 provider 检查只确认配置，不发送模型请求。

Jobs 将手动与定时任务限制为单个活动任务。Journal 保存有界业务阶段记录和异常类型/源码位置；Agent Run Trace 另由 TraceStore 保存字段白名单时间线；容量 Trace 又是单独的进程内环形样本。三者用途不同，均不应存消息正文、模型响应或工具参数/结果。

根目录 openapi.yaml 是管理 API 契约源；dashboard/src/contracts/generated.ts 由类型生成命令维护，Zod 继续验证运行时输入。详情见[管理界面操作指南](../../guides/webui.md)和[控制台开发说明](../../guides/development.md)。

## 运行轨迹查询

`GET manage/traces` 在两个已认证入口共用 `services/trace_query.py`。它消费 TraceStore 的白名单快照，不访问业务表或宿主对象。无参数时兼容原响应；可组合以下可选条件：

| 参数 | 含义 |
|---|---|
| `run_id` | 精确匹配生成的 32 位小写十六进制运行编号，不接受用户或会话标识 |
| `status` | `all`、`running`、`completed`、`error`、`interrupted` |
| `since` / `until` | 带时区的时间，按运行最后事件时间筛选，包含边界；结束不能早于开始 |
| `state` | 既有召回标记筛选，默认 `all`；各标记可重叠 |

查询只覆盖保留窗口内的事件，响应包含匹配运行的全部可用步骤，时间范围不会截断其开头。容量与保留元数据不变；非法条件返回 400，错误不回显参数。页面只通过 ManagementClient 查询，切换条件后清除旧结果并丢弃迟到响应。时间输入按设备时区转换；错误事件直接标出失败步骤，未结束运行只显示最后已知步骤，不推断失败原因。缺失或被淘汰步骤仍标为 partial。

当前没有记忆导入任务 API；人格包导入不等同于记忆导入。控制台不生成虚构的导入进度，任务状态接入留待真实服务提供接口。

## 人格控制台读模型（GitHub #82 / #83）

以下路由复用已认证的 WebRoutes 边界，以 OpenAPI 为契约源，生产页面通过 Zod 校验响应。

| 操作 | 有界输出或命令 |
|---|---|
| `GET manage/graph` | 最近更新的最多 120 个 Artifact、240 条真实或派生关联；不返回 Source 正文，遮蔽 secret/designated/shadow 内容 |
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

## 星图快照与操作

`manage/graph` 固定读取最近更新的最多 120 个节点和 240 条关联，不接受 `limit` 查询参数。仓储在 SQL 内排序并限制节点数，再读取该快照内的关联；不再将全部 Artifact 解码或逐节点查询边。`total` 通过计数查询取得。当前未增加数据库索引：超大库仍有排序扫描成本，应使用实际数据规模测量。

前端搜索、类型/时间/范围/对象筛选只作用于当前快照。每次加载或刷新只读取一批最多 120 条记忆；默认显示 80 条，可选 40/80/120。切换数量在前端完成，不重新请求后端，也不预取更大的节点快照。球面网格是装饰，选中后的关联与“只看关联记忆”使用真实图边。“寻找记忆”抽屉提供每页 30 条的键盘列表，选中后可聚焦、打开详情与审计。减少动态效果时跳过入场和持续动画；暂停按钮也可停止动效。

保存人格蓝图使用 `crypto.getRandomValues` 生成随机 ID，兼容普通 HTTP 页面；不依赖仅安全上下文提供的 `crypto.randomUUID`。这不改变宿主登录与接口鉴权要求。
