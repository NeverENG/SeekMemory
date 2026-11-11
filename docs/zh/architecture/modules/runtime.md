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

`contracts/runs.py` 定义同 lane 运行控制契约，并由 `app.runtime.contracts` 导出。`RunKind` 区分用户、延迟和主动运行；`RunTrigger` 携带显式时间与可选的 `RuntimeInput`，调用方负责在策略执行前接纳用户输入并排除过期/重放；该数据对象本身不执行接纳。`ActiveRunView` 只暴露运行标识、lane、代次、类型、开始时间及 `action_started`，不含正文或工具参数。`RunTransition.supersede_active` 表达旧计划的逻辑失效，只阻止未开始动作，不表示宿主调用已经终止、动作已撤销或任务已让位。`start_new=True, supersede_active=False` 在没有有效运行时允许启动；存在有效运行时保留旧句柄，`begin()` 返回空，替换须先显式应用覆盖意图。`RunPolicy.decide(state, trigger, active)` 是同步纯策略，不修改输入、不执行 I/O，也不决定全局优先级或 `YIELD`；若保留旧运行，调用方须有可靠待处理入口并保证之后重评估，否则使用默认覆盖策略。

`runs.py` 提供独立的内存组件 `RunControl` 与 `RunHandle`，由同一事件循环线程使用。`lane_id` 是实例内的覆盖范围，不等于记忆 `subject_key` 或全局会话身份；只有已经确认宿主与机器人实例隔离的路径才能复用现有 `session_id`，不据此生成或修改持久化会话键。`begin(lane_id, trigger)` 仅在没有有效当前句柄时创建运行，否则返回空，不自动覆盖；获准替换时，由调用方先执行 `supersede(lane_id, run_id)`，首次失效返回真并保留原因，重复、已关闭或过期请求返回假。其他 lane 不受影响。`finish()` 幂等关闭本控制器创建的句柄，且仅当它是当前同一个句柄时移除活动记录；被替换旧运行的结束不清除新运行，其他控制器及复制句柄的结束不影响原运行。`current()` 不创建状态。

epoch 由控制器实例的单调计数器发放，同 lane 重开及跨 lane 交错后仍严格递增，但不保证逐 lane 从 1 开始或连续。控制器不为已结束 lane 保留代次字典，仅持有活动记录和实例计数；调用方释放已结束句柄后，其 lane 身份可被回收。epoch 不跨实例或重启比较，也不表示全局调度优先级；运行身份仍结合 run_id 与实际句柄校验。

句柄只保存元数据、独立 `closed` 状态、无控制器引用的私有归属标记及可等待的 `superseded` 信号，不持有触发对象、消息、prompt、工具参数或宿主任务。`is_valid()` 仅在未关闭且未覆盖时为真；`raise_if_invalid()` 对关闭句柄抛出 `RunClosedError`，对被覆盖句柄抛出 `RunSupersededError`，均区别于 `asyncio.CancelledError`。结束不设置 superseded 信号，关闭后的覆盖请求也不改写结束原因。`mark_action_started()` 在端口调用边界同步检查有效性并记录开始；只读 `view()` 是元数据快照，不替代实时有效性检查。已开始标记在关闭/覆盖后仍保留，已开始工作可继续返回真实结果；标记不表示成功、失败或已收到回执，也不提供外部调用的原子撤销或回执核对。

有效性信号不代表已请求宿主 abort 或已安全让位；宿主 abort、全局调度和恢复由各自边界处理。句柄不跨线程、跨进程控制，也不在重启后恢复。

## 运行准入与输入接纳

`AgentRuntime(..., run_control_enabled=True, run_policy=None)` 显式启用同 lane 运行准入。组装方须提供专用 `RunRecorder`，在同一事件循环线程使用，并先确认宿主、机器人实例隔离，再以 `session_id` 作为 lane。`accept_user()` 要求稳定的事件 ID（显式参数优先于 `RuntimeInput.event_id`），并独自执行注意力评估；启用时不接受预计算 `decision`。默认仍关闭，不改变现有宿主组装、回执线协议、持久化键或公开配置；模型、动作和宿主发送检查点尚未接入。

输入先完成 Source 及投影记录，再评估注意力并保存状态。`RecordedTurn.replayed` 标识当前 recorder 生命期内重复返回的回执，不以数据库已有 Source 推断接纳已完成。状态保存失败仍可重试，后台补完投影也不会消耗第一次接纳机会。重放返回 `IGNORE/replayed_event`，不推进状态或覆盖运行；过期输入保留 Source 证据。二者均不返回可确认消息的游标。相同或未知时间不等于重放；缺少可靠时间时，以成功接纳的先后为准，失败重试也遵循此顺序。这里是进程内记录，不保证崩溃后严格单次处理。

`begin_run(lane_id, trigger, receipt=receipt)` 要求本 Runtime 返回的原始 `UserRunReceipt`、匹配的输入，以及仍等于当前 lane 最新未读序号、尚未被交付确认的游标。只有 `REPLY` 回执可启动 USER，成功后仅消费一次；`WAIT`/`OBSERVE` 输入仍可使旧计划失效，但不启动用户运行。接纳本身不预占运行；若期间有后台运行开始，启动时重新应用策略。准入记录在领取或调用方释放回执后清理，不保留历史 lane 索引；失败的接纳保留待重试。Recorder 原有已完成回执缓存不在此处清理，因此这不代表整个 Runtime 的内存已受限。

`DefaultRunPolicy` 允许空闲 lane 启动，新用户输入覆盖同 lane 旧计划，后台触发则保留有效运行和到期标记。注入策略只收到独立状态快照和只读运行视图；异常或错误返回类型会回退默认策略；当前没有待处理输入重评估入口，因此 USER 策略拒绝启动或要求保留有效旧运行时也会回退。诊断仅保存生成的运行元数据、事件码和异常类型，不记录正文、lane/Source ID 或异常消息。覆盖不删除 Source、不确认未读，也不把已开始动作记作取消；`WAIT` 期间的新输入仍重新评估注意力。

## 主动策略与动作审计

`DefaultProactivePolicy` 是确定性的纯状态策略。它要求显式传入 `now`，返回下一次可执行时间，并检查到期时间、安静截止时间、冷却、重试、忽略连击退避和尝试次数上限。它不做 I/O、不调用模型、不修改状态；默认关闭，只有 runtime composition 明确启用后才会生效。`plan_proactive_dispatch` 按到期时间排序可执行会话，应用每轮派发上限，并将超出部分作为仍然到期的任务留待后续轮次。宿主通过 `AgentRuntime.schedule_proactive()` 持久化显式到期时间；AstrBot 在启用 proactive 后由消息入口按 `proactive_idle_seconds` 排期。`TopicSource` 从 Source-backed 缓冲投影中提供记忆由头；没有候选时 worker 清除该次主动机会，不发送空主动。

`ActionExecutor` 是 Runtime 发起 action 的唯一执行/审计协调者：先写 attempt，再调用 `ActionPort`，最后写 terminal；可选的 `RunHandle` guard 在尝试前及宿主调用前同步检查，过期时不调用宿主；若尝试已记录则记 `cancelled`。宿主调用一旦开始，即便随后被覆盖也按实际回执记录，不伪称撤销。此检查点尚未接入 Runtime 派发或宿主发送路径，不等于已启用旧回复抑制。`ActionMessageSender` 只是 `SEND_TEXT` 的兼容适配器。`ActionLedger` 记录动作尝试及至多一个终态（`succeeded`、`failed` 或 `cancelled`）。幂等键由会话、run、动作类型和宿主 callback key 稳定生成；callback key 本身不会落盘。`RepoActionSink` 通过 `RuntimeEpisodeRepository` 写入元数据。审计仅保留标识符、时间戳、受限原因码、尝试序号和状态，不保存消息正文、prompt、工具参数或结果。

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

用户消息的已完成回执与待补偿写入都以现有 Source ID 为内部键，保留会话、说话人及正文的身份边界。不同会话可复用 event_id；同一消息重放不会重复写入。对外 turn_id 仍保留原 event_id（缺失时使用 Source ID）。

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

记忆上下文构造使用纯 `RecallService.query()`。前台召回和 AgentRuntime 的 `SeekMemoryContextAdapter` 因而共用服务注入的隐私策略；Runtime 不持有第二份隐私矩阵，也不重新披露原始候选。明确包含记录通过可选通用 `MemoryContextRecorder` 转发；普通宿主钩子在附加到请求后调用，后台在模型调用前立即调用。运行时不包含指定记忆规则；旧 `RecallService.build()` 仍是兼容的查询加记录入口。

现有注意力与主动选择策略分别由 `app/runtime/policy/attention.py`、`proactive.py` 维护；旧 `app.runtime.attention`、`proactive` 导入保留为同一模块对象的兼容入口。工具策略暂留 `app/runtime/tools.py`，因为它还包含宿主形状的过滤入口；`contracts/` 仍声明数据和端口，`runtime.py`、`dispatch.py`、`actions.py` 等仍负责执行与副作用。本次仅移动文件，不改变策略、调度或中断语义。

`app/runtime/contracts/context.py` 定义 `MemoryContextRequest` 和 `MemoryContext` 数据契约；`app/runtime/port/capabilities.py` 声明此前位于 `contracts/ports.py` 的外部能力协议（时钟、模型、记忆、发送与仓储等）。旧 `contracts/ports.py` 只转发同一对象以保留导入路径；原本与状态和动作 DTO 紧邻的 `SessionStateStore`、`ActionPort` 等协议暂留各自契约文件，不为目录整齐而改变声明所有权。
