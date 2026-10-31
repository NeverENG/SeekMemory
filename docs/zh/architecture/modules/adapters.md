# adapters：AstrBot 宿主适配

## 职责

adapters 把 AstrBot 事件、provider 和消息发送映射到应用端口。宿主对象不进入 core、recall 或 app/runtime 的领域策略中。

## 组合根

独立控制台的组合根位于 `adapters/console/runtime.py`，HTTP 入口位于 `adapters/console/server.py`。它复用管理与召回用例、现有存储及 PersonaPacks，不加载 AstrBot SDK，也不启动聊天、模型或后台维护。认证和本机来源限制由 HTTP 适配层负责，详见 [WebUI](webui.md)。

AstrBotPlugin 在 start 时建立 Store、Cache、TreeService、Graph、HybridRetriever、Source-backed Buffer、CheckpointManager、各应用服务、AgentRuntime、Jobs、WebRoutes 与后台服务；stop 时依次停止后台任务与管理任务、注销本实例路由、保存缓冲、flush checkpoint，最后关闭 Store。

main.py 定义插件入口并委托 lifecycle；组合和 wiring 位于 adapters/astrbot/plugin.py。AstrBotPlugin 显式持有 hooks 与 attention 组件，不再通过多继承共享宿主状态。AstrBotHooks 在 adapters/astrbot/hooks.py 把宿主 hook 映射为服务调用：访问策略、输入接收、记忆注入、助手回复捕获、实际发送后的交付记录、运行时/工具观测。它不实现抽取、容量或维护算法。

启动和停止共用生命周期锁。初始化中途失败也会释放已创建的资源；停止先等待后台任务与管理任务退出，再保存缓冲、flush checkpoint 和关闭存储，并清空服务、执行器、缓存及宿主引用。停止被取消时仍先完成清理，再传播取消，允许安全重启。

## 端口适配

- AstrBotRuntimeAdapter 复用 astrbot.events.to_runtime_input 转换消息，保留 scene、role、addressed、线程与消息 ID 等已有字段，并管理宿主 event extra 中的 user/reply Source ID、turn ID、final recall IDs 和 episode 去重标记。事件发生时间与进程接收时间分别记录。
- AstrBotModelGateway 提供延迟回复使用的 ModelGateway。
- AstrBotActionPort 同时提供 ActionPort 和 MessageSender：execute 接收 ActionRequest 并返回 ActionResult，既有 send 接口委托 execute 后返回布尔值。
- ProviderChatModel 将宿主 extraction/persona provider 包装为 ChatModel。
- SeekMemoryContextAdapter 将 Runtime 的 MemoryContextPort 接到现有 RecallService。
- RelationshipInteractionPolicy 从 Cache 读取按 subject 唯一且已验证的 Relationship 快照，把既有 Runtime decision 与已记录 Source ID 转成无正文 InteractionGate。AstrBot hook 执行拒绝和固定语气 directive，不把关系语义放进 app/runtime。

动作请求中的正文仅用于执行，不属于 ActionRecord 审计字段。不支持的动作返回 unsupported_action；空正文、缺少会话、宿主不可用、发送拒绝和执行异常分别返回固定原因码。宿主异常正文不会返回给调用方；取消继续向上传递，由运行时安排恢复。适配器只报告执行结果，不负责重试、动作审计去重或终态判定。

AstrBot 的时间转换集中在 astrbot/time.py 的 utc8_time_hook：用户消息、普通回复、延迟回复和运行审计均在适配层经过同一钩子，再调用既有 RunRecorder。新写入时间采用带 +08:00 的 ISO 字符串，保留明确时区；内核读取视图仍采用原有的无时区格式。字段、内核接口和数据库结构不变。

AstrBotBuffer 复用 Buffer 的入队与话题算法，AstrBotSourceView 复用 SourceStore 的原文查询；两者通过同一时间钩子转换投影，覆盖待处理消息和已处理父消息的读回。历史 Source 不改写。带时区的旧值正常换算；缺失、无效或没有时区的旧值保留原样，不猜测历史机器时区，也不凭此生成绝对事件时间或队列年龄。旧值本身是否错误、已生成的记忆是否需要修订，仍需结合原运行环境另行核对。

运行时决策仍使用 epoch 时间戳，不依赖操作系统时区。时间适配不修改 core、Buffer 或抽取原型，不改变夜间维护的调度配置。

AccessService 基于完整 session UMO、sender ID、owner/trusted 配置和 observe_groups 决定观察/召回；宿主事件信息只在边界处转换。配置和 database path 仍由插件组合根读取。

## 当前边界

宿主 hook 注册必须绑定真实插件模块路径，避免热重载后回调无法识别。Runtime 的工具过滤在模型请求前运行；工具调用完成后的观测 hook 不能作为强制拦截。插件初始化/宿主 API 不可用时，由上层状态和 fail-open 处理，不应把 AstrBot 依赖泄漏到业务模块。

## 本机回环记忆适配层

`adapters/loopback/runtime.py` 组装现有 Store、Buffer、RecallService 和 StatusService；`adapters/loopback/server.py` 负责本机 HTTP、令牌验证、请求映射及资源关闭。`scripts/serve.py` 只负责解析命令行并保留原来的启动方式（`python scripts/serve.py --data-dir <dir>`）。这属于宿主传输与组合根，不属于 core 规则或 services 用例；不依赖 AstrBot SDK。`scripts/runtime_http.py` 仍是独立的 AgentRuntime 桥接验证入口，不与记忆服务混为一体。

此入口的 `/capture` 保存 Source 并排队，`/recall` 读取已有 Artifact；`/extract/plan` 空队列返回 204，有任务但尚无可执行 ChatRequest 时返回 501；`/extract/commit` 也返回 501。不能把只含 Source ID 的伪计划或有待抽取的空召回当成端到端成功。契约和冒烟脚本对未完成项报告 `INCOMPLETE` 并返回非零退出码；只有真正在已抽取内容上验证召回、隐私与预算才报告全通过。HTTP 错误不向调用方回显底层异常文本；无认证的健康检查不暴露本地数据库路径。新建数据目录使用仅所有者权限，运行时令牌元数据以仅所有者权限原子替换；调用方仍需保证传入的既有数据目录本身私有。数据格式、公开配置和端点路径不变。

## DSH 协议桥

DSH 的 RuntimeBridge 复用 KernelClient 的本机认证连接。服务在 healthz 声明 runtime_contract: 1 后，桥接器通过 POST /runtime/events 传递输入、回复、交付、错误及动作执行结果，通过 POST /runtime/context 获取 MemoryContext。公共字段以 app/runtime/contracts/ 为准，共享非空样例同时由 Python 和 Node 测试校验。消息时间按已知毫秒或带时区字符串转为 epoch 秒；未知时间为 0，不猜历史时区。

subject_key 表示稳定记忆归属，session_id 表示本轮运行会话，二者不混用。pre-step 只在消息 ID 匹配时使用对应的 Source 回执与事件时间；服务的 runtime_gate_enabled 明确开启后，才把其 RunDecision 映射为宿主放行或拒绝，不实现第二套注意力策略。

旧服务或不支持此运行时协议的服务沿用 capture/recall。运行时写请求一旦发出，即使失败或超时，也不再补发 legacy capture，避免重复保存。普通 assistant/message 只映射为 record_reply，没有发送完成证明时不调用 record_delivery。桥接器不新增模型循环、调度器、主动发送或工具执行能力；`scripts/runtime_http.py` 是只做组合的真实 Python loopback 服务，`runtime-python-smoke.mjs` 启动它并让 DSH RuntimeBridge 驱动真实 AgentRuntime。

DSH 每个宿主上下文只注册一次；卸载会撤销钩子、取消桥接请求并清空上下文缓存，迟到的响应不再注入。仓库现在还提供 `scripts/runtime_http.py` 真实 Python 本机服务入口，以及让 DSH RuntimeBridge 驱动它的 Node 集成测试。

关系模式默认为 observe：RelationshipInteractionPolicy 可以计算无正文的候选交互档案，但默认不会注入 directive 或拒绝回复。拒绝回复必须同时满足显式 `relationship_mode=enforce` 和现有 `runtime_gate_enabled=true`；allowed/neutral 关系不会启用该 gate。仅在显式启用 enforcement 时，low/dislike 的普通私聊陈述才按 Source ID 做稳定 `0.8`/`0.5` 采样；真实问题和宿主 direct signal 仍是 required reply。相同的显式 enforcement 控制下，low/dislike 群聊 ambient 被拒绝。Relationship Artifact 不进入 Recall 或管理目录。

## 明确接口及宿主依赖

`adapters/domain.py` 导出不依赖 SDK 的共享人格文件及关系适配，`adapters/ports.py` 复用应用协议。`adapters/astrbot/domain.py` 导出 AstrBot 集成入口，有意依赖其 SDK；不依赖 SDK 的事件、运行时、时间、动作及上下文映射仍可从各自原文件导入。`adapters/astrbot/ports.py` 声明有限的 `HookHost`、`ProviderHost` 和 `MessageHost` 视图。

钩子和注意力不再转发任意未知属性，`_bindings` 明确提供有文档和类型的宿主能力视图；独立测试转接可在本地绑定相同字段。宿主仍唯一持有就绪状态、服务、仓储及运行审计清理时间戳。钩子内部工具关联与宿主资源所有权分开。

| 文件 | 职责及副作用 | 逻辑复杂度及耦合 |
|---|---|---|
| `astrbot/plugin.py` | 按依赖顺序构造资源，按生命周期顺序关闭 | 高：组装根，不实现记忆算法 |
| `astrbot/hooks.py`、`attention.py` | 映射回调并应用既有运行时、权限及交互决策 | 中至高：有限有类型宿主视图，不任意转发 |
| `astrbot/registration.py` | 稳定回调模块、名称、优先级及顺序 | 低：仅 SDK 注册，旧 hooks 导入保留别名 |
| `astrbot/events.py`、`runtime.py` | 事件、回执及附加关联映射 | 中：不导入 SDK 事件类型或实现持久化规则 |
| `astrbot/actions.py`、`model.py`、`context.py` | 宿主发送、提供方调用及明确上下文记录转发 | 低：注入的窄宿主能力 |
| `astrbot/time.py`、`topics.py` | 既有 UTC+8 写读视图及原始消息支持的话题候选 | 中：转换及队列视图，不添加时间规则 |
| `persona_packs.py`、`relationship_policy.py` | 人工本地文件及已验证关系视图 | 中：格式及访问规则仍由原职责文件管理 |

`tests/test_adapter_interface_contract.py` 保护共享导出及协议；运行时插件测试保护有限依赖及回调身份、顺序。既有宿主生命周期、取消、上下文、动作及时间钩子检查仍需执行。UTC+8 实现以移除说明字符串后的语法树比较，确认逻辑不变。管理路由、Node 及前端实现不在结构整理范围内。

后台 RunContext 使用的已观察机器人身份归宿主持有。仅用于回调的工具尝试归 AstrBotHooks 管理，资源清理后清空，避免重启后将旧工具回执交给新执行器完成。宿主生命周期回归覆盖身份捕获、停止清理及重启。

已提交编号的缓存补偿通过 `app.CacheRepairs` 共享；组装根将同一实例注入检查点、抽取、上下文及维护写入协调器。业务计划仍归各用例，按所有者计数避免无关补偿混入检查点待处理总数。
