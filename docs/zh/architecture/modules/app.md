# app：端口、DTO 与应用策略

## 职责

app 提供用例间共享的数据、外部能力声明和应用策略。目前也包含夜间整理、强化写回、运行时执行编排及部分存储转接，不能把整个目录视为纯规则层。

## 配置归属

配置默认值由宿主无关的 `app/config/` 按宿主身份、抽取、召回、维护、可观测性、关系及 Runtime 分组维护。空配置可直接启动；AstrBot 的 `_conf_schema.json` 是旧键的兼容输入与界面投影，不再决定默认值。Console 使用同一配置入口。当前服务仍可传入已有的回退参数；后续迁移配置读取时须保留既有默认行为。

Runtime 调度选项由 `app/config/runtime.py` 提供只读类型化快照；启动时确定等待时长，worker 轮询时重新读取以保持既有动态覆盖语义。

## 两个接口入口

- [app/domain.py](../../../../app/domain.py)：应用层提供什么。显式导出共享类型、函数和执行类；只做导出与说明，实现在原文件中。
- [app/ports.py](../../../../app/ports.py)：调用方需要提供什么。显式列出所需协议及回调类型别名；只声明或导出，不实现读写。

这是接口入口的集中整理，范围包括 app 顶层公开能力、运行时已有 `__all__` 及其他实际跨模块调用。原有导入路径保留，现有调用方尚未统一迁移；运行时数据与协议的原定义也暂未搬动。常量仍由所属策略文件维护，不把内部常量全部提升为应用接口。

### domain：共享数据

| 接口 | 用途 | 定义文件 |
| --- | --- | --- |
| `DialogueTurn`、`ExtractionState` | 缓冲消息视图、抽取队列状态 | `app/contracts.py` |
| `ChatRequest`、`ChatResponse`、`WriteOutcome` | 模型输入输出、写入与用量汇总 | `app/contracts.py` |
| `RecallRequest`、`RecallResult` | 较窄的召回请求和结果；当前生产 `RecallService.build` 仍使用参数和元组，未采用这两个类型 | `app/contracts.py` |
| `ContextBudget` | 请求限额，附带估算和展示方法 | `app/budget.py` |
| `FlushDecision`、`ExtractionBatch` | 是否抽取及原因、单会话批次 | `app/flush_policy.py` |
| `DreamResult`、`PersonaEvidence` | 夜间整理结果、人格修订的证据概述 | `app/dream.py`、`app/persona_synthesis.py` |
| `RuntimeInput`、`RunContext`、`UserRunReceipt`、`RunResult` | 入站事件、待执行任务、接收回执和交付结果 | `app/runtime/contracts/events.py` |
| `AttentionLevel`、`WakeAction`、`AttentionDecision`、`RunDecision` | 注意力、回复动作及判断结果 | `app/runtime/contracts/events.py` |
| `SessionState`、`ProactiveDecision` | 可变会话调度状态、主动发言条件判断 | `app/runtime/contracts/sessions.py`、`proactive.py` |
| `MemoryContextRequest`、`MemoryContext` | 只读记忆上下文的输入和输出 | `app/runtime/contracts/context.py` |
| `ActionKind`、`ActionStatus`、`ActionRequest`、`ActionResult`、`ActionRecord` | 动作类别、状态、执行输入输出和无正文审计 | `app/runtime/contracts/actions.py` |
| `RecordedTurn`、`RecordedReply` | 原始消息写回后的标识与数量 | `app/runtime/recorder.py` |
| `ProactiveCandidate`、`ProactiveDispatchPlan`、`DueRun`、`TopicCandidate` | 主动会话选择、到期任务及话题候选 | `app/runtime/policy/proactive.py`、`scheduler.py`、`topics.py` |
| `EpisodeRecord`、`EpisodeOutcome`、`ToolCall`、`ToolGuardDecision` | 运行审计结果、工具观察及过滤判断 | `app/runtime/episode.py`、`tools.py` |

### domain：规则与可执行能力

下表中的“复杂度”指理解调用条件、状态和失败流程的难度，不是代码行数或运行耗时。

| 接口 | 职责与副作用 | 逻辑复杂度 / 耦合 |
| --- | --- | --- |
| `budget_from_config` | 读取调用方提供的配置，规整为预算对象 | 低 / 低 |
| `estimate_tokens`、`estimate_messages` | 按字数和消息数估算用量，不是精确分词 | 低 / 低 |
| `clamp_chars` | 裁剪文本，同时返回原长度 | 低 / 低 |
| `decide_flush` | 判断夜间、过期、每日上限、积压和空闲条件 | 中 / 低 |
| `select_topic_batches` | 按会话轮转选择话题 | 中 / 低 |
| `chunk_turns` | 分割超长话题，尽量保留问答配对 | 中 / 低 |
| `pack_same_session_batches` | 按预算合并同会话分块，不再次拆分完整分块 | 中 / 低 |
| `build_persona_request` | 构造人格修订请求，不调用模型 | 中 / 低 |
| `parse_persona_draft` | 校验模型草稿；相同文本返回空，非法内容报错 | 中 / 低 |
| `CheckpointManager` | `record/due/pending/flush`：合并命中，提交版本后更新缓存 | 中 / 高 |
| `DreamCycle` | `enabled/due/run/status`：判断每日整理时机、循环抽取、维护和写台账 | 高 / 高 |
| `DefaultAttentionPolicy` | `evaluate`：返回回复或观察决定及后续轮次调整 | 低 / 低 |
| `DefaultProactivePolicy`、`plan_proactive_dispatch` | 判断主动条件，对到期会话排序和限量；不读写状态 | 中 / 低 |
| `TimingPolicy`、`Scheduler` | `evaluate/due/proactive_due`：判断时间条件，读取状态并选出任务；不发送 | 低 / 中 |
| `AgentRuntime` | 接收消息、构建上下文、交付回调、延迟/主动执行及状态迁移 | 高 / 高 |
| `RuntimeWorker` | `dispatch/dispatch_proactive/tick/run_forever`：轮询、并发限额和进程内会话去重 | 高 / 高 |
| `RunRecorder` | 创建运行编号，记录用户/助手 Source、待抽取视图、命中和交付审计 | 高 / 高 |
| `action_idempotency_key` | 按会话、运行、动作及回调标识计算稳定编号 | 低 / 低 |
| `ActionLedger`、`ActionExecutor` | `begin/finish/execute`：构造尝试记录、调用宿主动作并记录终态 | 中 / 中 |
| `ActionMessageSender` | `send`：将旧式文本发送转交给动作接口 | 低 / 中 |
| `EpisodeRecorder` | `record`：将一条运行审计交给存储 | 低 / 低 |
| `safe_error_code`、`normalize_tool_calls` | 仅保留受限错误码及工具名，去掉异常正文、工具参数和结果 | 低 / 低 |
| `episode_outcome`、`delivery_failure_outcome`、`delivery_failure_metadata` | 归类交付/工具失败，返回结果对象或字段映射 | 低 / 低 |
| `ToolPolicy`、`tool_result_failed`、`trace_tool_call` | 判断和过滤工具，观察调用及失败元信息；过滤部分操作宿主形状的对象 | 中 / 高 |
| `RunTracer` | 关联宿主事件的运行编号，记录请求、回复、工具及交付诊断 | 中 / 高 |
| `InMemoryStateStore`、`JsonStateStore`、`RepoStateStore` | `get/put`：内存、文件或注入仓储的会话状态实现 | 中 / 中 |
| `JsonlEpisodeStore`、`RepoEpisodeStore`、`RepoActionSink` | `append`：写文件或将审计转交注入仓储 | 中 / 中 |

`AgentRuntime` 的方法按职责分为：输入 `observe/accept_user`；上下文 `build_context`；回调 `record_reply/record_delivery/record_error`；执行 `dispatch_deferred/dispatch_proactive`；状态迁移 `schedule_proactive/clear_proactive/clear_wait/claim_dispatch/schedule_retry/mark_delivered`。这些方法保留为兼容入口；状态计算已移入内部 transitions，后台执行已移入 dispatch，进程内交付补偿由 writeback 管理；新增 `retry_writebacks()` 仅补写，不调用模型或发送。

### ports：外部提供的能力

具名协议按已有职责集中列出，不表示这些协议可以相互替换。连接、文件路径、缓存和后台任务的创建与关闭仍由组装方负责。

| 协议 | 方法 | 外部负责什么 |
| --- | --- | --- |
| `ChatModel` | `complete` | 接收通用模型请求并返回文本和用量 |
| `Retriever` | `retrieve` | 从给定记忆池返回检索候选 |
| `SourceStore` | `append_sources/recent_sources/source_umo/source_umos/sources_by_ids` | 追加原始证据，按时间或编号读取证据及来源会话 |
| `ArtifactStore` | `get/by_source_ids/list/list_recent/list_impressions/count_impressions/count/history/inspect_record`；`commit/commit_many/add_edge/edges_between/edges_of/set_parent` | 记忆版本读写、证据账本提交及连接维护；多次连接/父节点调用不自动组成整体事务 |
| `TreeArtifactStore` | `get/commit/list/edges_of/add_edge/set_parent` | 树读写所需的六个存储操作 |
| `ArtifactCache` | `version/load/put/get/active/by_level/by_subject/remove/size`，以及 `artifacts` | 有效记忆的派生读视图；提交成功后更新 |
| `TreeCache` | `get/put/by_level` | 树所需的三个缓存操作；未命中不等于数据库不存在 |
| `ExtractionStore` | `enqueue_extraction/pending_extractions/queue_counts/release_deferred/ready_extraction_ids/mark_extraction_succeeded/mark_extraction_failed` | Source 引用排队、成功标记和失败重试 |
| `MetricsStore`、`LedgerStore` | `capacity_usage`；`entries/verify` | 容量统计、业务账本读取和校验 |
| `DreamRunStore` | `get/begin/finish/recent` | 完整夜间台账生命周期，失败可被编排识别 |
| `StateRepository`、`EpisodeRepository`、`ActionRepository` | `get/put`；`append`；`append_action` | 运行时转接使用的原始仓储能力，不包含 SQL |
| `PersonaPacks`、`DreamJournal` | `catalog/read/bundle/artwork/save/remove`；`recent` | 人格包管理、近期整理记录读取 |
| `Clock`、`SessionStateStore` | `__call__`；`get/put` | UTC 时间戳秒数、可变会话状态读写 |
| `MemoryContextPort`、`ModelGateway` | `build_context`；`complete` | 只读记忆上下文、运行时模型文本调用 |
| `MessageSender`、`ActionPort`、`ActionSink` | `send`；`execute`；`append` | 兼容文本发送、宿主动作执行、无正文动作审计 |
| `ProactivePolicy`、`TopicSource` | `evaluate`；`candidates` | 主动发言的纯判断、只读话题来源 |
| `SourceSink`、`PendingSink`、`CheckpointSink` | `append_sources`；`add`；`record` | 运行时写回所需的原始证据、待处理视图、命中接收 |
| `EpisodeWriter`、`EpisodeSink` | `record`；`append` | 运行审计接收及存储，两个不同调用环节 |
| `TraceSink`、`TraceWriter` | `record`；`append` | 诊断事件接收及行写入，不替代业务审计 |

夜间整理使用六个具名回调：`FlushFn`（限量抽取）、`PendingFn`（待处理数量）、`MaintainFn`（维护）、`UsageFn`（累计模型用量）、`Log`（状态输出）、`DreamClock`（日期时间对象）。其中 `FlushFn` 是可调用协议，计入上述协议，其余五项是类型别名。`DreamClock` 是原 `app.dream.Clock` 的别名，与返回浮点秒数的运行时 `Clock` 不同。

### 接口相似不等于实现重复

| 相关接口或实现 | 判断 |
| --- | --- |
| `ArtifactStore` 与 `TreeArtifactStore`；`ArtifactCache` 与 `TreeCache`；`SourceStore` 与 `SourceSink` | 后者表达更窄的使用需求，复用同一实现即可；不需要为每个协议维护一份存储实现 |
| `ChatModel` 与 `ModelGateway` | 都调用模型，但请求格式及是否返回用量不同；目前是两套调用约定，后续需核对供应商接线再决定是否统一 |
| `EpisodeWriter`、`EpisodeRecorder`、`EpisodeSink` | 形成 `record → record → append` 链；中间类目前只转交，没有独立业务规则，存在简化空间 |
| `CheckpointManager.flush` 与 `core.strength.reinforce` | 都包含权重增加计算，但前者还累计命中、限制上限并提交版本；不能直接替换，应先明确强化规则的唯一归属 |

### 外部依赖状态

接口集中不等于依赖已经全部规范化。以下列出已声明能力和仍待后续盘点的依赖：

| 使用位置 | 实际要求 | 当前缺口 |
| --- | --- | --- |
| `DreamCycle.dreams` | `get/begin/finish/recent` | 已使用 `DreamRunStore`；控制台仍只要求 `DreamJournal.recent` |
| `budget_from_config`、`DreamCycle` | 配置读取函数 | 使用 `Callable`，配置键仍由各策略读取 |
| `CheckpointManager.artifacts/cache` | 版本提交、缓存读取和更新 | 已使用 `ArtifactStore`、`ArtifactCache` |
| `RunRecorder.cache` | 按编号读取记忆 | 已标注已有 `ArtifactCache`；进一步缩窄留待调用方盘点 |
| `RepoStateStore/RepoEpisodeStore/RepoActionSink` | `get/put`、`append`、`append_action` | 已使用 `StateRepository`、`EpisodeRepository`、`ActionRepository` |
| `RuntimeWorker` | 开关、会话列表、任务构造、间隔和重试参数回调 | 各自使用匿名 `Callable`；调用关系需结合构造函数阅读 |
| `RunTracer`、`ToolPolicy.filter_tool_set` | 事件 `get_extra/set_extra`；工具集 `tools/remove_tool` | 宿主对象形状进入应用实现，未被明确隔离 |

## 提交与证据约束

ArtifactStore.commit 要求 expected_revision；commit_many 用于一组必须原子完成的版本写入。存储实现需满足这些协议，但协议本身不实现 IO。

`TreeArtifactStore` 和 `TreeCache` 是 TreeService 所需的窄接口，也集中声明在 `app/ports.py`，分别包含六个存储方法和三个缓存方法；实现由 `store/` 提供。它们不再由 core 声明或导出。缓存未命中不表示数据库中不存在，缓存 `put` 不负责落库；连接和缓存的生命周期由调用方管理。

CheckpointManager 依赖调用方只传入最终上下文实际保留的 Artifact；自身不会判断内容是否真的注入。冷却期内的重复命中被忽略，其他命中累计到待提交状态，随后以 Artifact revision 和 StateEvent 一起提交。人格请求构造与草稿解析不负责证据选择、修订资格或落库；这些仍由调用服务负责。

## 副作用归属

ChatModel 是无会话状态的调用端口。app 的 budget、flush 和 wake/timing 策略不负责连接数据库或调度宿主任务。DreamCycle、CheckpointManager 和 AgentRuntime 则会协调外部读写；`runtime/state.py`、`episode.py` 中的现有文件实现会直接访问文件系统，`RunTracer` 和工具过滤仍操作宿主形状的对象。SQL 继续只由 store 实现。

## 逻辑与文件分层

| 层次 | 文件 | 职责与限制 |
| --- | --- | --- |
| 接口与数据 | `domain.py`、`ports.py`；`contracts.py`、`console_ports.py`、`runtime/contracts/` | 两个集中入口只声明、导出和说明；原数据及协议定义位置兼容保留 |
| 纯规则 | `budget.py`、`flush_policy.py`、`persona_synthesis.py`、`dream_policy.py`；运行时 attention、proactive、transitions、topics 的排序 | 只根据输入计算，不调用模型、不持久化、不读取时钟 |
| 流程编排 | `checkpoint.py`、`dream.py`；运行时 runtime、dispatch、writeback、recorder、scheduler、worker、动作执行 | 通过注入能力读写；区分领取、生成、发送、确认、写回及补偿 |
| 外围转接 | 运行时 state、episode、actions 中的现有存储实现，以及 tracing、工具过滤 | 暂留原文件；连接、文件路径及任务生命周期由组装方管理；SQL 仍仅在 store |

内部依赖方向为：`AgentRuntime → Dispatch / DeliveryWritebacks → transitions / RunRecorder / 外部端口`。纯状态计算不反向依赖运行时入口；执行不持有整个 Runtime。调度只读选择任务；worker 管理同进程并发与会话去重，并复用既有循环补写。两条后台路径保留独立提示和失败规则。dispatch 的较长实现保留这两条完整流程，避免通过大量回调把编排重新分散。

## 提交与交付恢复

| 阶段 | 失败行为与恢复责任 |
| --- | --- |
| 强化数据库提交失败 | 保留未提交命中，不更新缓存；后续 flush 重试 |
| 强化提交成功、缓存失败 | 已提交命中不再强化；单独读取数据库最新版本修复缓存 |
| 模型或发送失败 | 保留既有有限重试与取消传播；发送返回 False 同样视为失败 |
| 确认发送成功、状态或写回失败 | 保留进程内交付凭据，返回 `delivered=True / writeback_pending`，仅补未完成写入 |
| 夜间台账结束失败 | 返回 `failed / journal_finish_failed` 及已完成数量，不回滚此前记忆提交 |

`CheckpointManager.flush()` 只统计本次新提交，`pending()` 按编号统计待提交和待补缓存并集；补偿期间的新命中独立保留。缓存缺失不等于数据库删除。

`RunRecorder` 按原始消息、队列投影、逐条强化和审计记录完成位置。`AgentRuntime.retry_writebacks()` 返回完成的补写项数，不调用模型或发送；worker 在发言开关判断前及停止时调用。同会话交付未补完时暂停新的后台发言，普通入站继续接收。普通回复保存失败时保留已准备编号供宿主关联交付；交付回调先确认有界已读位置，再补回复及审计；旧回调及补偿不清理新任务。

状态读取失败不伪装成空会话。状态及审计写入失败保留 `last_error` 并抛出，编排方重试；文件替换成功后才发布内存候选状态。新仓储审计编号稳定，旧记录、数据库结构和公开配置保持兼容。诊断回调失败不改变业务结果，错误不保存异常正文。

凭据及补偿只在当前进程保留，不能据此承诺崩溃、发送结果未知或跨进程场景严格单次交付。日期台账也不是分布式锁；夜间失败续跑不保证所有维护动作只执行一次。时区转换继续由适配层负责。

## 注释与验证入口

全部 app 模块及公开定义使用英文在前、中文等义说明；简单说明使用一行，复杂说明写职责、副作用、资源归属及失败约定。机器指令、字段值与提示词不翻译。

| 场景 | 现有验证入口 |
| --- | --- |
| 公开契约及依赖导出 | `tests/test_public_interfaces.py`、`tests/test_runtime_contracts.py` |
| 强化提交与最新缓存补偿 | `tests/test_reinforcement.py` |
| 夜间到期、预算、台账与诊断失败 | `tests/test_dream.py`、`tests/test_dream_eval.py` |
| 部分原始消息、队列及强化写回 | `tests/test_run_recorder.py` |
| 确认交付后各阶段失败、停止/关闭发言补写、存储失败 | `tests/test_runtime_writeback.py` |
| 已读确认、新消息保护及重启恢复 | `tests/test_runtime_delivery.py`、`tests/test_runtime_recovery.py` |
| 并发、主动策略及宿主接线 | runtime scheduler/worker/proactive 与 host 测试 |

## 后续仍待整理

- services/store/adapters 盘点后保留 app 中现有存储转接、EpisodeRecorder 及 perceive 的 ProviderChatModel：迁移会改变兼容路径或引入反向依赖；它们的资源由组装方管理。此轮不额外迁移。
- 去重结果、补偿完成结果及命中冷却记录的保留期限尚未定义，仍随实例释放；未完成补偿可能在内存保留待写正文。
- `RecallRequest/RecallResult` 尚未接入生产召回，`ChatModel/ModelGateway` 仍是不同约定。
- worker 配置回调仍是 Callable；宿主形状对象仍进入 tracing 和工具过滤，位置迁移留待后续。

代码入口：[domain.py](../../../../app/domain.py)、[ports.py](../../../../app/ports.py)；运行时交付约束见 [Agent Runtime](runtime.md)。

抽取回调可通过 `ExtractionFailure` 携带已完成的写入和话题数量。夜间整理将这些数量保留在失败结果与台账中；已准备写入的恢复仍由回调方负责。

记忆上下文构造使用纯 `RecallService.query()`。明确包含记录通过可选通用 `MemoryContextRecorder` 转发；普通宿主钩子在附加到请求后调用，后台在模型调用前立即调用。运行时不包含指定记忆规则；旧 `RecallService.build()` 仍是兼容的查询加记录入口。

## 共享规则及已提交编号补偿

`cache_repair.py` 仅管理已提交编号、归属标记和标记代次，读取数据库当前版本并刷新或移除缓存，不提交记忆或拥有业务计划。组装方将同一个 `CacheRepairs` 注入检查点、抽取、上下文及维护写入协调器；各用例仍持有自身未完成语义计划。按所有者读取编号保留检查点 `pending()` 计数。补偿期间相同编号的新标记会留待下次，避免后续工作丢失。缓存及连接构造和关闭仍由组装方管理。

`text_rules.py` 分别管理已证明等价的字母数字二元组（保留单字符）及单词字符二元组、Jaccard（保留下划线行为）。`recall.seed` 及维护兼容路径保留别名，不合并 Dice、Jaccard 或不同规范化规则。`value_codec.py` 管理原本相同的管理及状态旧对象解析器。`revision_plan.py` 读取当前版本并准备原本相同的树及旧持久化替换，父字段及图连接写入仍独立。既有合并默认值归合并规则管理，检查点复用领域命中增量，不合并无关相同数值。

共享文本帮助函数按每种变体 207 组固定及随机输入与修改前实现比较，行为一致；既有行为测试仍是权威验证。`tests/test_cache_repair_integration.py` 覆盖共享编号去重、所有者计数、连续失败及补偿中同编号重新标记。现有 app 持久化转接和提供方包装保留兼容安全路径，避免移动产生反向导入。
