# services：用例编排

## 职责

services 将领域对象、app 端口以及 perceive、recall、maintain 组合为完整业务用例。服务层不提供通用依赖注入容器，也不持有 SQL；ServiceCollection 是一个有类型的服务集合。

## 能力边界

| 服务 | 拥有的工作 |
|---|---|
| AccessService | 根据 owner/trusted/group 配置决定是否记忆、观察或召回 |
| RecallService | 计算预算与降级输入，调用唯一 recall pipeline；提供不写交付状态的预览 |
| IngestService | 选择待处理话题、解析 provider、调用模型、构造 Artifact 并负责生产写入、重试和 usage 汇总 |
| CapacityService | 读容量快照、运行 CapacityGovernor，并执行限流、释放 deferred、缩小批次/召回或维护动作 |
| MaintenanceService | 按顺序调用自我印象汇总、遗忘、相似合并和人格沉淀/综合 |
| ManagementService | 查询目录、详情、版本与证据；验证管理编辑和回滚；复用 RecallService 做诊断 |
| StatusService | 为管理页提供人格时间线和账本哈希链检查 |
| BackgroundService | 只负责周期、闲时与 Dream 调度；具体动作委托给上述服务 |

## 写入与失败

perceive/absorb.build_plan 是无副作用转换：验证 evidence、主体边界、去重和 family payload，返回可写入计划。真正调用 ArtifactStore.commit 的是 IngestService。提交要求 CAS 版本；数据库提交成功后更新 Cache，随后可做 best-effort 的图边和印象修订。

model/provider 失败时，IngestService 不把 pending Source 标记为已完成；ExtractionRepository 管理退避、最大尝试次数和 dead 状态。多会话批次中的单会话失败不会让其他已选会话完全停止。

## 调度与人工操作

BackgroundService 管 nightly/idle/Dream/weekly/checkpoint/runtime worker 的启动和停止。WebUI 的 Jobs 将手动和定时维护串行化为单个活动任务；插件停止时先取消和等待后台任务，再关闭数据库。服务不直接注册宿主事件，adapters 负责将事件送入服务。

入口：[service_collection.py](../../../../services/service_collection.py)、[ingest_service.py](../../../../services/ingest_service.py)、[recall_service.py](../../../../services/recall_service.py)、[maintenance_service.py](../../../../services/maintenance_service.py)。
