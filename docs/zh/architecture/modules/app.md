# app：端口、DTO 与应用策略

## 职责

app 提供用例间共享的数据、外部能力声明和应用策略。目前也包含夜间整理、强化写回、运行时执行编排及部分存储转接，不能把整个目录视为纯规则层。

## 两个接口入口

- [app/domain.py](../../../../app/domain.py)：应用层提供什么。显式导出 79 个类型、函数和执行类；只做导出与说明，实现在原文件中。
- [app/ports.py](../../../../app/ports.py)：调用方需要提供什么。显式列出 29 个协议及 5 个回调类型别名；只声明或导出，不实现读写。

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
| `MemoryContextRequest`、`MemoryContext` | 只读记忆上下文的输入和输出 | `app/runtime/contracts/ports.py` |
| `ActionKind`、`ActionStatus`、`ActionRequest`、`ActionResult`、`ActionRecord` | 动作类别、状态、执行输入输出和无正文审计 | `app/runtime/contracts/actions.py` |
| `RecordedTurn`、`RecordedReply` | 原始消息写回后的标识与数量 | `app/runtime/recorder.py` |
| `ProactiveCandidate`、`ProactiveDispatchPlan`、`DueRun`、`TopicCandidate` | 主动会话选择、到期任务及话题候选 | `app/runtime/proactive.py`、`scheduler.py`、`topics.py` |
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

`AgentRuntime` 的方法按职责分为：输入 `observe/accept_user`；上下文 `build_context`；回调 `record_reply/record_delivery/record_error`；执行 `dispatch_deferred/dispatch_proactive`；状态迁移 `schedule_proactive/clear_proactive/clear_wait/claim_dispatch/schedule_retry/mark_delivered`。这些仍是同一个类的方法，尚未完成内部拆分。

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
| `PersonaPacks`、`DreamJournal` | `catalog/read/save/remove`；`recent` | 人格包管理、近期整理记录读取 |
| `Clock`、`SessionStateStore` | `__call__`；`get/put` | UTC 时间戳秒数、可变会话状态读写 |
| `MemoryContextPort`、`ModelGateway` | `build_context`；`complete` | 只读记忆上下文、运行时模型文本调用 |
| `MessageSender`、`ActionPort`、`ActionSink` | `send`；`execute`；`append` | 兼容文本发送、宿主动作执行、无正文动作审计 |
| `ProactivePolicy`、`TopicSource` | `evaluate`；`candidates` | 主动发言的纯判断、只读话题来源 |
| `SourceSink`、`PendingSink`、`CheckpointSink` | `append_sources`；`add`；`record` | 运行时写回所需的原始证据、待处理视图、命中接收 |
| `EpisodeWriter`、`EpisodeSink` | `record`；`append` | 运行审计接收及存储，两个不同调用环节 |
| `TraceSink`、`TraceWriter` | `record`；`append` | 诊断事件接收及行写入，不替代业务审计 |

夜间整理使用六个具名回调：`FlushFn`（限量抽取）、`PendingFn`（待处理数量）、`MaintainFn`（维护）、`UsageFn`（累计模型用量）、`Log`（状态输出）、`DreamClock`（日期时间对象）。其中 `FlushFn` 是可调用协议，计入上述 29 个协议，其余五项是类型别名。`DreamClock` 是原 `app.dream.Clock` 的别名，与返回浮点秒数的运行时 `Clock` 不同。

### 接口相似不等于实现重复

| 相关接口或实现 | 判断 |
| --- | --- |
| `ArtifactStore` 与 `TreeArtifactStore`；`ArtifactCache` 与 `TreeCache`；`SourceStore` 与 `SourceSink` | 后者表达更窄的使用需求，复用同一实现即可；不需要为每个协议维护一份存储实现 |
| `ChatModel` 与 `ModelGateway` | 都调用模型，但请求格式及是否返回用量不同；目前是两套调用约定，后续需核对供应商接线再决定是否统一 |
| `EpisodeWriter`、`EpisodeRecorder`、`EpisodeSink` | 形成 `record → record → append` 链；中间类目前只转交，没有独立业务规则，存在简化空间 |
| `CheckpointManager.flush` 与 `core.strength.reinforce` | 都包含权重增加计算，但前者还累计命中、限制上限并提交版本；不能直接替换，应先明确强化规则的唯一归属 |

### 尚未明确声明的外部依赖

接口集中不等于依赖已经全部规范化。以下是当前代码实际要求、但未形成完整具名协议或未用于参数注解的能力：

| 使用位置 | 实际要求 | 当前缺口 |
| --- | --- | --- |
| `DreamCycle.dreams` | `get/begin/finish/recent` | 参数为 `Any`；`DreamJournal` 仅覆盖 `recent`，不能代表整个整理台账 |
| `budget_from_config`、`DreamCycle` | 配置读取函数 | 使用 `Callable`，配置键仍由各策略读取 |
| `CheckpointManager.artifacts/cache` | 版本提交、缓存读取和更新 | 依赖存在但构造参数未标注协议 |
| `RunRecorder.cache` | 按编号读取记忆 | 使用 `Any`，没有表达最小能力 |
| `RepoStateStore/RepoEpisodeStore/RepoActionSink` | `get/put`、`append`、`append_action` | 注入仓储未声明窄协议 |
| `RuntimeWorker` | 开关、会话列表、任务构造、间隔和重试参数回调 | 各自使用匿名 `Callable`；调用关系需结合构造函数阅读 |
| `RunTracer`、`ToolPolicy.filter_tool_set` | 事件 `get_extra/set_extra`；工具集 `tools/remove_tool` | 宿主对象形状进入应用实现，未被明确隔离 |

## 提交与证据约束

ArtifactStore.commit 要求 expected_revision；commit_many 用于一组必须原子完成的版本写入。存储实现需满足这些协议，但协议本身不实现 IO。

`TreeArtifactStore` 和 `TreeCache` 是 TreeService 所需的窄接口，也集中声明在 `app/ports.py`，分别包含六个存储方法和三个缓存方法；实现由 `store/` 提供。它们不再由 core 声明或导出。缓存未命中不表示数据库中不存在，缓存 `put` 不负责落库；连接和缓存的生命周期由调用方管理。

CheckpointManager 依赖调用方只传入最终上下文实际保留的 Artifact；自身不会判断内容是否真的注入。冷却期内的重复命中被忽略，其他命中累计到待提交状态，随后以 Artifact revision 和 StateEvent 一起提交。人格请求构造与草稿解析不负责证据选择、修订资格或落库；这些仍由调用服务负责。

## 副作用归属

ChatModel 是无会话状态的调用端口。app 的 budget、flush 和 wake/timing 策略不负责连接数据库或调度宿主任务。DreamCycle、CheckpointManager 和 AgentRuntime 则会协调外部读写；`runtime/state.py`、`episode.py` 中的现有文件实现会直接访问文件系统，`RunTracer` 和工具过滤仍操作宿主形状的对象。SQL 继续只由 store 实现。

## 内部逻辑的整理顺序

纯规则部分的关系较清楚：预算 → 批次选择；人格请求构造 → 草稿校验；注意力/主动策略 → 调度选择。它们不调用模型或维护数据库事务，可以保留当前分工。

后续按以下顺序澄清，尚未实施：

1. **写回与夜间整理**：先明确 `CheckpointManager` 的待提交状态、提交和缓存恢复阶段，以及 `DreamCycle` 的抽取、维护、预算停止和台账结果。两者的依赖需要完整声明；是否迁入 services 留待 services 盘点后决定。
2. **运行时状态与执行**：`AgentRuntime` 同时管理状态迁移、调用模型、发送和写回；延迟与主动路径各自维护生成、发送及失败处理。先列明共同阶段和各自规则，再决定合并位置，不能直接把两条路径当成相同行为。
3. **失败后的资源交接**：延迟发送后的 Source/审计写回位于模型/发送异常处理块之外；`CheckpointManager.flush` 又在同一异常处理块内执行提交与缓存更新。需要分别说明“未提交”“提交成功但缓存失败”“已发送但写回失败”的恢复责任，不能把它们统称一次执行失败。
4. **存储和宿主转接**：`state.py` 混合状态解析与三种存储；`episode.py` 混合结果归类和文件/仓储写入；`actions.py` 混合编号规则、审计、执行与仓储转接；`tracing.py` 和工具过滤依赖宿主形状。先与 store/adapters 的职责核对，再移动实现。
5. **状态释放与未接入接口**：`RunRecorder` 的运行去重集合、Checkpoint 的命中冷却表没有单项淘汰流程，仅随实例释放。`RecallRequest/RecallResult` 未接入生产召回。需要明确保留期和真实调用方，再决定收敛或删除。

app 文件的显式导入关系中未发现循环；动态导入和实际运行行为仍需单独验证。接口入口的集中不改变上列实现位置与恢复责任。

代码入口：[domain.py](../../../../app/domain.py)、[ports.py](../../../../app/ports.py)；运行时行为详见 [Agent Runtime](runtime.md)。
