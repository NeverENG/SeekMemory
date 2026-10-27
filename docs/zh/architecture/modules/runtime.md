# Agent Runtime：会话注意力与运行时动作

## 职责

app/runtime 定义不依赖 AstrBot 的会话状态、注意力决策和运行时动作生命周期。它处理“何时观察、何时回复或等待”及延迟回复的协调，不取代 SeekMemory 的 Extraction、Recall 或普通 AstrBot 工具循环。

## 对象与策略

- RuntimeInput 是从宿主事件裁剪出的输入；RunContext 是一项待执行任务的上下文。
- SessionState 保存 wait、retry、quiet、cooldown、unread/read-through、dispatch 尝试等会话运行状态。它不是 Source 或 Artifact。
- WakePolicy 对输入给出 ignore、observe、wait、reply 之一。私聊和 @/直接提及是强注意力；明确问题可直接回复；quiet/cooldown 影响 ambient 流量。
- TimingPolicy 是纯 wait/retry 截止时间策略。Scheduler 只读持久化状态并返回 due runs；RuntimeWorker 轮询、去重并分发，不拥有记忆规则。
- MemoryContextPort 将运行时输入交给既有 RecallService；Runtime 本身不实现第二套记忆检索。

## 两条运行路径

**普通 AstrBot 回复**：hook 将用户消息交给 AgentRuntime.accept_user；RunRecorder 写用户 Source/队列；请求 hook 由 runtime.build_context 取得记忆；模型与宿主发送完成后，capture/delivery hooks 经 AgentRuntime/RunRecorder 记录助手 Source、召回强化和 EpisodeRecord。

**延迟 ambient 回复**：开启 runtime_gate_enabled 后，worker 根据已到期 wait/retry 选择会话；Runtime 领取 dispatch、构建记忆上下文、调用 ModelGateway、通过 MessageSender 发送，再记录助手 Source 与 EpisodeRecord。失败会按每会话上限和指数退避重试。该路径直接调用 provider，不运行完整 AstrBot agent/tool 循环。

runtime_gate_enabled 默认 false。关闭时，等待和后台 deferred dispatch 不活跃；普通事件捕获、记忆注入和审计仍由插件 hook 承担。

## 写回与诊断

RunRecorder 是 Source、pending projection、checkpoint 和 episode 的唯一运行时写回协调者，以 run_id 和确定性 Source ID 防止重复回调重复写入。runtime_episodes 是追加式业务审计元数据；RunTracer/TraceStore 是受字段白名单约束的诊断时间线。二者不保存对话正文，不互相替代。

ToolPolicy 在模型请求前可从 req.func_tool 移除不允许的工具；观察工具调用的 hook 只是诊断信号，不能单独阻止执行。实际过滤由 runtime_tool_filter_enabled 控制，默认关闭。
