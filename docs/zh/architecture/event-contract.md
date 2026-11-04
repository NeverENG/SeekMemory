# EVENT-CONTRACT.md · 入站事件边界

> 当前实现：`adapters/host_gateway/` 的 `HostRequest` 与 `HostGateway`；
> 决策视图为 `app/runtime/contracts/` 的 `RuntimeInput`（#222）。

## 决策

宿主适配器只提取 SDK 或线协议的事实，由 HostGateway 统一构造 `RuntimeInput`。
`HostRequest` 是临时、已压缩的消息事实，不保存、不代表完整宿主事件；
不引入无损 `HostEvent` / `ContentPart` / `EventCodec` 三层结构。

```text
AstrBot SDK 事件 ──astrbot.events 提取──▶ HostRequest ─┐
DSH 事件 ──Node 映射、现有 HTTP input──▶ HostRequest ─┴─▶ HostGateway ─▶ RuntimeInput ─▶ AgentRuntime
```

DSH 仍在 Node 侧提取平台字段，Python `runtime_http.py` 将既有 `input` 字段装成
`HostRequest`，不修改 HTTP 请求形状。AstrBot `to_runtime_input` 兼容入口同样经过网关。
`session_id` 仍是现有会话身份；`event_id` 用于消息关联或现有去重，不能作为身份认证。
目前信任上层适配器提供的事实，网关不做认证、限流、并发过滤、好感度或披露决策；
AgentRuntime 负责调度，实际披露与动作检查仍在各自边界。

`RuntimeInput` 保留既有的可选上下文字段，已有运行时决策及持久会话含义不变：

| 字段 | 用途 |
|---|---|
| `scene` | private / group / channel / thread / **comment**（评论区） |
| `conversation_id` | 群号 / 频道 / 线程标识 |
| `thread_id` | 评论嵌套 / 楼中楼；不填表示无嵌套 |
| `self_id` | 机器人自身标识 |
| `role` | owner / admin / member / bot / system |
| `addressed` | 是否被叫名字或唤醒前缀命中 |
| `reply_to_me` | 是否引用/回复了她 |
| `event_id` | 宿主消息关联及既有去重标识 |
| `kind` | message / edit / recall / reaction（预留，当前只处理 message） |

## 发送能力与主动由头

- **不新增 `reply_capable`**：运行时只判断"该不该说"；能不能发（平台限制、频率、评论权限）
  由发送端口负责，失败返回失败/异常，运行时按 fail-open 记录（#123 决策）。
- **主动由头只来自记忆 + 定时窗口**：`TopicSource` 只从记忆挑候选（未聊完的 scene、
  印象变化、关系冷却），是否到点由 `ProactivePolicy`（#117）决定，不做随机触发。

## 理由

1. **只有两个宿主**（AstrBot、DSH），加一层保真事件结构收益低于维护成本。
2. **富内容已在 Source 层承接**：图片、语音、引用在捕获阶段转成文本占位与 media 家族，
   决策层不需要 `ContentPart`。
3. **策略真正需要的是信号，不是事件**：关系分、相关度、热度、时间窗由
   `RuntimeInput` 的通用字段和宿主传入的可选信号表达，策略不应依赖平台名称。
4. **入站投影有单一归属**：临时事实只在边界流转；不复制原始事件、Source 或领域策略。

## 演进触发条件（满足任意一条再评估无损 HostEvent）

1. 需要处理**非消息事件**（编辑、撤回、表情回应、入群/退群、在线状态）并据此决策；
2. 接入**第三个平台**且字段差异大到 `RuntimeInput` 无法表达（例如线程/评论层级、匿名身份）；
3. 需要**多模态输入**（语音转写、图片内容）直接参与注意力决策，而不是在 Source 层归一化；
4. 出现"同一宿主多个事件源"需要合并（例如机器人同时收到群消息与私聊转发）。

若以后确需无损事件，再单独评估新契约及迁移；当前 `HostRequest` 不承担原始事件真源。

## 多平台目标

已确认要接的平台：Telegram、微信、抖音、B站（外加现有 AstrBot/QQ 与 DSH）。
它们的差异主要在**会话形态**（频道/评论/私聊）与**发送能力**（能否语音/引用/撤回），
这两点分别由 `scene` / `conversation_id` 和后续的发送端口表达，不需要无损事件结构。
