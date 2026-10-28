# app：端口、DTO 与应用策略

## 职责

app 定义用例间共享的数据形状和可替换端口，放置轻量的纯策略。它让业务代码依赖接口，而不是直接依赖 SQLite、AstrBot provider 或前端传输结构。

## 边界对象

- DialogueTurn 是带 session、speaker、role、正文、时间和 Source/turn/topic/reply 引用的缓冲视图。
- ExtractionState 表示 Source 对应的队列状态，不复制正文。
- ChatRequest / ChatResponse 是 provider-neutral 模型调用格式；usage 和延迟等元数据可选。
- WriteOutcome 汇总写入、跳过、错误、重试性和 token usage。
- RecallRequest / RecallResult 提供更窄的召回调用边界。

app/ports.py 定义 ChatModel、Retriever、SourceStore、ArtifactStore、ArtifactCache、ExtractionStore、LedgerStore 和 MetricsStore。ArtifactStore.commit 要求 expected_revision；commit_many 用于一组必须原子完成的版本写入。存储实现需满足这些协议，但协议本身不实现 IO。

`TreeArtifactStore` 和 `TreeCache` 是 TreeService 所需的窄接口，也集中声明在 `app/ports.py`，分别包含六个存储方法和三个缓存方法；实现由 `store/` 提供。它们不再由 core 声明或导出。缓存未命中不表示数据库中不存在，缓存 `put` 不负责落库；连接和缓存的生命周期由调用方管理。

## 策略与用例辅助

- **budget.py** 将系统提示、记忆注入、群上下文和历史条数约束在统一配置视图中，并提供字符到 token 的估算。估算用于预算和观测，不代表 tokenizer 精确计量。
- **flush_policy.py** 决定是否到抽取时机、按会话轮转选择话题、为超长话题分块，并在可行时保留用户与其助手回复配对。话题批次保持单会话。
- **checkpoint.py** 只接收最终上下文实际保留的 Artifact。它在冷却窗口内合并重复命中，随后以 Artifact revision 和 StateEvent 一起提交强化。
- **dream.py** 编排每天最多一次可恢复的抽取/维护周期，管理批次、call/token 预算、usage 汇总和 Dream 台账；具体抽取、维护逻辑由服务注入。
- **persona_synthesis.py** 限定人格综合输入长度并解析模型草稿，不写库、不选 evidence、不决定是否有资格修订。
- **app/runtime/** 定义独立的 AgentRuntime 策略和运行时端口，详见 [Agent Runtime](runtime.md)。

## 副作用归属

ChatModel 是无会话状态的调用端口。app 的 budget、flush 和 wake/timing 策略不负责连接数据库或调度宿主任务。应用服务负责调用端口并选择事务时机，store 负责持久化，adapters 提供宿主实现。

代码入口：[ports.py](../../../../app/ports.py)、[contracts.py](../../../../app/contracts.py)、[budget.py](../../../../app/budget.py)。
