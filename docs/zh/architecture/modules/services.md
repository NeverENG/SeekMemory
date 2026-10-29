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
| TreeService | 统一查询子节点和印象，协调记忆版本提交、缓存及父子关系更新 |

## 写入与失败

perceive/absorb.build_plan 是无副作用转换：验证 evidence、主体边界、去重和 family payload，返回可写入计划。真正调用 ArtifactStore.commit 的是 IngestService。提交要求 CAS 版本；数据库提交成功后更新 Cache，随后可做 best-effort 的图边和印象修订。

model/provider 失败时，IngestService 不把 pending Source 标记为已完成；ExtractionRepository 管理退避、最大尝试次数和 dead 状态。多会话批次中的单会话失败不会让其他已选会话完全停止。

TreeService 的实现集中在 `services/tree_service.py`，通过 `app/ports.py` 的 `TreeArtifactStore`、可选 `TreeCache` 访问数据，不导入存储实现。子节点读取优先用缓存，未命中再查库且不回填缓存；印象查询仅在缓存对应层级为空时回退数据库。

`add_under` 拒绝自身作为父节点，随后依次提交记忆、更新缓存、写父字段和父子连接；这些步骤不是整体事务，错误向调用方传递，提交失败不会更新缓存。对已有记忆可先生成新版本，但返回值仍是原输入对象。设置父字段不清理旧连接，清空父字段也不删除旧连接。宿主目前只构造该服务，树写入由冒烟和契约检查覆盖，尚未接入生产抽取流程。

## 调度与人工操作

BackgroundService 管 nightly/idle/Dream/weekly/checkpoint/runtime worker 的启动和停止。WebUI 的 Jobs 将手动和定时维护串行化为单个活动任务；插件停止时先取消和等待后台任务，再关闭数据库。服务不直接注册宿主事件，adapters 负责将事件送入服务。

入口：[service_collection.py](../../../../services/service_collection.py)、[ingest_service.py](../../../../services/ingest_service.py)、[recall_service.py](../../../../services/recall_service.py)、[maintenance_service.py](../../../../services/maintenance_service.py)。

## 接口与文件归属

`services/domain.py` 明确导出受支持的服务。`services/ports.py` 声明所需缓冲区、模型提供方、诊断、日志、任务及追踪能力，复用 app 已有仓储和缓存协议。两个入口文件不含业务实现；旧包入口和实现路径仍指向同一对象。所有注入资源的构造与关闭均由组装方管理。

| 实现文件 | 职责及副作用 | 逻辑复杂度与耦合 |
|---|---|---|
| `ingest_service.py` | 话题选择、模型调用及有顺序的抽取写入 | 高：协调模型、持久提交、缓存及队列 |
| `maintenance_service.py` | 读取证据、调用模型及编排维护 | 高：协调多个写入流程，不实现 SQL |
| `persona_policy.py` | 选择证据、规范化配置权重及构造版本 | 低至中：只处理给定数据的纯规则 |
| `management_service.py` | 兼容的管理入口 | 低：委托明确的查询与命令 |
| `management_queries.py` | 目录、详情、人格包及版本视图 | 中：读取仓储，不写入记忆 |
| `management_commands.py` | 校验已确认的修改、设定安装、回滚及人格包操作 | 中：先提交再更新缓存，不拥有资源 |
| `background_service.py` | 任务生命周期及执行频率 | 中：拥有自有任务，业务工作交给其他服务 |
| `access_service.py`、`recall_service.py`、`capacity_service.py`、`status_service.py`、`tree_service.py` | 既有权限、召回、压力、状态及树用例 | 分别负责各自职责；树的后续写入不是整体事务 |

`tests/test_services_interface_contract.py` 验证接口对象身份，以及顶层和插件命名空间下的全新导入顺序。原有抽取、人格、管理 HTTP 和架构场景验证委托后的行为，不能据此声称真实模型或真实宿主已经通过验证。
