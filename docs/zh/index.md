# SeekMemory 文档

SeekMemory 为长期对话提供可追溯、可修订的记忆。文档描述当前仓库代码，不保存 Issue、PR、RFC 或历史基线副本。

## 从这里开始

- [架构总览](architecture/overview.md)：核心数据模型、分层边界和写入/召回流程。
- [模块设计](architecture/modules/core.md)：按代码模块查看职责与协作方式。
- [开发环境与验证](guides/development.md)：后端、控制台、接口和测试层的常用操作。
- [管理界面操作](guides/webui.md)：记忆库、诊断、维护任务和运行轨迹。
- [人格种子文件](guides/persona-seed.md)：校验、初始化和后续演化。

## 模块

| 模块 | 设计说明 |
|---|---|
| core | [领域对象与纯策略](architecture/modules/core.md) |
| app | [端口、DTO、预算与应用策略](architecture/modules/app.md) |
| services | [用例编排](architecture/modules/services.md) |
| store | [SQLite、版本链与缓存](architecture/modules/store.md) |
| perceive | [对话缓冲与抽取](architecture/modules/perceive.md) |
| recall | [候选检索、披露与组装](architecture/modules/recall.md) |
| maintain | [生命周期、合并与人格](architecture/modules/maintain.md) |
| Agent Runtime | [会话注意力与运行时动作](architecture/modules/runtime.md) |
| adapters | [AstrBot 宿主适配](architecture/modules/adapters.md) |
| WebUI | [管理 API 与控制台](architecture/modules/webui.md) |

## 架构图

### AgentRuntime V3 · 平台抽象与中断
<img src="../assets/v3-runtime-interruption-premium.png" alt="AgentRuntime V3 平台抽象与中断" width="100%">

同会话新意图替换旧 run；跨会话零抢占；取消是协作式的，不等同于暂停。

### 记忆内核 · 算法因子
<img src="../assets/v3-memory-algorithm-premium.png" alt="记忆内核与算法因子" width="100%">

Source 是不可变证据，Artifact 是可修订解释；召回由强度、相关性、证据闸门、披露和预算共同决定。

### 梦境架构 · 人格链与记忆强化
<img src="../assets/v3-dream-persona-architecture-premium.png" alt="梦境架构、人格链与记忆强化" width="100%">

Dream 在离线周期中分类、强化、合并、遗忘和修订，并把稳定行为沉淀进同一人格链。
