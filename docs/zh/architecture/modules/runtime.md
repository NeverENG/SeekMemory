# Agent Runtime：会话注意力与运行时动作

## 职责

app/runtime 定义不依赖 AstrBot 的会话状态、注意力决策和运行时动作生命周期。它处理“何时观察、何时回复或等待”及延迟回复的协调，不取代 SeekMemory 的 Extraction、Recall 或普通 AstrBot 工具循环。

## 对象与策略

- RuntimeInput 是从宿主事件裁剪出的输入；RunContext 是一项待执行任务的上下文。
- SessionState 保存 wait、retry、quiet、proactive、unread/read-through、dispatch 尝试等会话运行状态。它不是 Source 或 Artifact。
- `DefaultAttentionPolicy` 只给出“是否回复”：主人、私聊和直接提及回复；非主人被直接提及后，为该说话人保留 3 轮后续回复窗口；其余消息观察。它不包含群聊、关系、热度或额度算法。
- TimingPolicy 是纯 wait/retry 截止时间策略。Scheduler 只读持久化状态并返回 due runs；RuntimeWorker 轮询、去重并分发，不拥有记忆规则。
- MemoryContextPort 将运行时输入交给既有 RecallService；Runtime 本身不实现第二套记忆检索。
- ActionPort 接收临时 ActionRequest（session_id、kind、text），返回 ActionResult（ok、reason）。MessageSender 的布尔发送接口保持兼容；ActionRecord 仍只保存无正文审计信息，执行结果不负责决定审计终态。

## 主动策略与动作审计

`DefaultProactivePolicy` 是确定性的纯状态策略。它要求显式传入 `now`，返回下一次可执行时间，并检查到期时间、安静截止时间、冷却、重试、忽略连击退避和尝试次数上限。它不做 I/O、不调用模型、不修改状态；默认关闭，只有 runtime composition 明确启用后才会生效。`plan_proactive_dispatch` 按到期时间排序可执行会话，应用每轮派发上限，并将超出部分作为仍然到期的任务留待后续轮次。宿主通过 `AgentRuntime.schedule_proactive()` 持久化显式到期时间；AstrBot 在启用 proactive 后由消息入口按 `proactive_idle_seconds` 排期。`TopicSource` 从 Source-backed 缓冲投影中提供记忆由头；没有候选时 worker 清除该次主动机会，不发送空主动。

`ActionExecutor` 是 Runtime 发起 action 的唯一执行/审计协调者：先写 attempt，再调用 `ActionPort`，最后写 terminal；`ActionMessageSender` 只是 `SEND_TEXT` 的兼容适配器。`ActionLedger` 记录动作尝试及至多一个终态（`succeeded`、`failed` 或 `cancelled`）。幂等键由会话、run、动作类型和宿主 callback key 稳定生成；callback key 本身不会落盘。`RepoActionSink` 通过 `RuntimeEpisodeRepository` 写入元数据。审计仅保留标识符、时间戳、受限原因码、尝试序号和状态，不保存消息正文、prompt、工具参数或结果。

`SessionState` 保存会话级调度状态和按说话人分开的 `followup_by_speaker` 后续回复计数。它不是记忆主体；说话人身份仍由 `speaker_id` 表达。

## 两条运行路径

**普通 AstrBot 回复**：hook 将用户消息交给 AgentRuntime.accept_user；RunRecorder 写用户 Source/队列；请求 hook 由 runtime.build_context 取得记忆；模型与宿主发送完成后，capture/delivery hooks 经 AgentRuntime/RunRecorder 记录助手 Source、召回强化和 EpisodeRecord。

accept_user 返回的 UserRunReceipt 包含本轮接收时的消息确认序号 read_through_seq。宿主只在事件上携带该序号，并在发送完成时传回 record_delivery；运行时只确认该序号及以前的消息，保留此后到达的未读消息和等待任务。重复或乱序确认不能使已读位置或最近发言时间倒退。缺少序号的旧调用、过期事件只更新交付时间，不清空未读。待抽取队列不是未读计数；宿主不从队列长度推算会话未读数。

**延迟 ambient 回复**：开启 runtime_gate_enabled 后，worker 根据已到期 wait/retry 选择会话；Runtime 领取 dispatch、构建记忆上下文、调用 ModelGateway、通过 MessageSender 发送，再记录助手 Source 与 EpisodeRecord。失败会按每会话上限和指数退避重试。该路径直接调用 provider，不运行完整 AstrBot agent/tool 循环。

等待和重试期限在模型与发送执行期间保留，尝试次数在调用前持久化。取消会安排有限重试并继续抛出取消信号；进程中断后，原有 Scheduler 可从同一状态恢复。重试次数跨重启保留，新 Source 使用自己的次数预算。只有成功确认对应消息或旧任务耗尽时才清理相应任务，不能覆盖期间新消息安排的期限。运行时保存领取时的状态快照以区分旧标记与新任务，不增加数据库字段、表或第二套调度循环。

成功发送后重新读取注入时钟，作为交付审计和最近发言时间的起点；失败或取消后也重新读时钟，从失败时刻开始退避。显式传入的 now 是该次运行的时间下界。RuntimeWorker.dispatch 统一管理并发名额与会话去重；轮询、直接调用共用此入口。排队也占用会话去重标记，取得名额后复查开关、时钟和到期状态，取消会释放名额与标记。这只保证单个 worker 进程中的协调，不保证跨进程严格单次发送。

runtime_gate_enabled 默认 false。关闭时，等待和后台 deferred dispatch 不活跃；普通事件捕获、记忆注入和审计仍由插件 hook 承担。

## 写回与诊断

RunRecorder 是 Source、pending projection、checkpoint 和 episode 的唯一运行时写回协调者，以 run_id 和确定性 Source ID 防止重复回调重复写入。runtime_episodes 是追加式业务审计元数据；RunTracer/TraceStore 是受字段白名单约束的诊断时间线。二者不保存对话正文，不互相替代。

### 运行轨迹事件边界

`app/runtime/tracing.py` 的 RunTracer 是宿主无关生产者，事件仅需要 get_extra/set_extra 关联状态；`core/domain/operations/trace.py` 拥有字段清理与运行投影，`store/run_trace.py` 拥有 JSONL 持久化。管理查询消费同一快照，见 [WebUI](webui.md#运行轨迹查询)。

| 事件 | 记录时机 |
|---|---|
| `agent_begin` | 运行开始，关联随机生成的 run_id |
| `llm_request` / `llm_response` | 请求编号、召回白名单摘要与可用耗时；不含模型输入输出 |
| `tool_call` / `tool_result` | 工具名及可用耗时；不含参数或返回正文，未知结果保持 unknown |
| `agent_done` | 运行结束状态 |
| `message_sent` | 已观察到发送成功；独立于记忆注入 |

公共事件字段只有 run_id、sequence、at、event、request_index、status、duration_ms、tool、recall。recall 仅保留有界生成 ID、计数、固定 mode/fallback/disclosure 枚举和 gate 数值；不保存消息、提示词、响应、来源正文、工具参数/结果、用户/会话标识或凭据。写入和重载均重新清理未知字段。事件状态为 running/ok/error/unknown；运行状态沿用投影：结束错误为 error，其他结束或发送成功为 completed，重启前未结束为 interrupted，其余为 running。

TraceStore 默认保留 7 天、最多 5000 条事件。生产者清理过期与超量记录；诊断写入失败不阻断主流程，并通过 persistence_error 提示记录可能不完整。记录保留或缺失不能用来证明未执行某步骤。独立控制台在启动时只读加载离线文件；替换快照后需重启服务，不与运行中的宿主共用数据目录。

ToolPolicy 在模型请求前可从 req.func_tool 移除不允许的工具；观察工具调用的 hook 只是诊断信号，不能单独阻止执行。实际过滤由 runtime_tool_filter_enabled 控制，默认关闭。

## 交付后补写

Runtime 在确认发送后立即保留进程内交付凭据。会话确认、Source/队列及审计分阶段完成；失败返回 `RunResult(delivered=True, error="writeback_pending")`，不重新生成或发送。`AgentRuntime.retry_writebacks()` 返回完成的补写项数；worker 每轮在发言开关判断前调用，停止时再次尝试。同一会话旧交付未补完时，后台新发言暂停，普通消息仍接收。普通回复即使原始消息保存失败，也返回已准备编号供宿主关联交付；交付回调先确认会话，再补原始消息及审计。

RunRecorder 保留原始消息、投影及逐条强化的完成位置，失败仅重试缺失阶段。新仓储审计的稳定编号来自会话和 run_id，历史记录不改写。状态读取错误不再伪装成空会话，状态/审计写入失败保留 last_error 并抛出；编排方负责重试，诊断仍不影响业务。文件替换失败保留磁盘和内存中的旧状态。

凭据及补偿不跨进程持久化。突然退出或发送结果未知仍可能重试，不能据此承诺跨重启单次发送。

## 内部文件及资源

运行时入口保留在 runtime.py；transitions.py 只计算独立状态副本，dispatch.py 通过端口执行后台任务，writeback.py 管理已确认交付的补偿。三者不反向依赖 AgentRuntime；recorder.py 唯一协调原始消息/队列/强化/审计写回。现有 state、episode、actions 内的存储转接以及宿主 tracing、工具过滤暂留原处。源码说明统一英文在前、中文等义，接口清单见 app 模块文档。

文件审计补偿以原有 `session_id/run_id` 字段识别完整已保存行；追加结果不确定时重新读取已保存编号，防止再次追加。此去重仅覆盖同实例及重建实例后的完整行，不是跨进程文件锁，也不增加文件字段。

记忆上下文构造使用纯 `RecallService.query()`。明确包含记录通过可选通用 `MemoryContextRecorder` 转发；普通宿主钩子在附加到请求后调用，后台在模型调用前立即调用。运行时不包含指定记忆规则；旧 `RecallService.build()` 仍是兼容的查询加记录入口。

现有注意力与主动选择策略分别由 `app/runtime/policy/attention.py`、`proactive.py` 维护；旧 `app.runtime.attention`、`proactive` 导入保留为同一模块对象的兼容入口。工具策略暂留 `app/runtime/tools.py`，因为它还包含宿主形状的过滤入口；`contracts/` 仍声明数据和端口，`runtime.py`、`dispatch.py`、`actions.py` 等仍负责执行与副作用。本次仅移动文件，不改变策略、调度或中断语义。

`app/runtime/contracts/context.py` 定义 `MemoryContextRequest` 和 `MemoryContext` 数据契约；`app/runtime/port/capabilities.py` 声明此前位于 `contracts/ports.py` 的外部能力协议（时钟、模型、记忆、发送与仓储等）。旧 `contracts/ports.py` 只转发同一对象以保留导入路径；原本与状态和动作 DTO 紧邻的 `SessionStateStore`、`ActionPort` 等协议暂留各自契约文件，不为目录整齐而改变声明所有权。
