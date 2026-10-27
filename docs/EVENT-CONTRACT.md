# EVENT-CONTRACT.md · 事件分层决策

> 状态：**已决策（v0.4.2）**。本文记录"为什么现在不引入 HostEvent 分层"，
> 以及什么条件下需要重新评估。权威实现：`app/runtime/contracts.py` 的 `RuntimeInput`。

## 决策

宿主事件（AstrBot / DSH / 未来平台）由**适配层直接映射为 `RuntimeInput`**，不引入
中间的 `HostEvent` / `ContentPart` / `EventCodec` 三层结构。

```text
宿主原始事件 ──适配层映射──▶ RuntimeInput（决策输入）──▶ AttentionPolicy / ProactivePolicy
```

`RuntimeInput` 在 v0.4.2 做了**向后兼容扩展**（全部字段带默认值）：

| 字段 | 用途 |
|---|---|
| `scene` | private / group / channel / thread |
| `conversation_id` | 群号 / 频道 / 线程标识 |
| `self_id` | 机器人自身标识 |
| `role` | owner / admin / member / bot / system |
| `addressed` | 是否被叫名字或唤醒前缀命中 |
| `reply_to_me` | 是否引用/回复了她 |
| `event_id` | 宿主动作幂等键 |
| `kind` | message / edit / recall / reaction（预留，当前只处理 message） |

## 理由

1. **只有两个宿主**（AstrBot、DSH），加一层保真事件结构收益低于维护成本。
2. **富内容已在 Source 层承接**：图片、语音、引用在捕获阶段转成文本占位与 media 家族，
   决策层不需要 `ContentPart`。
3. **策略真正需要的是信号，不是事件**：关系分、相关度、热度、时间窗由
   `app/runtime/signals.py` 表达，可被 attention / proactive / recall 三处复用。
4. **并行开发的边界**：#114/#116/#117 正在改 `contracts.py` 与适配器；新增一层会扩大冲突面。

## 演进触发条件（满足任意一条再引入 HostEvent）

1. 需要处理**非消息事件**（编辑、撤回、表情回应、入群/退群、在线状态）并据此决策；
2. 接入**第三个平台**且字段差异大到 `RuntimeInput` 无法表达（例如线程/评论层级、匿名身份）；
3. 需要**多模态输入**（语音转写、图片内容）直接参与注意力决策，而不是在 Source 层归一化；
4. 出现"同一宿主多个事件源"需要合并（例如机器人同时收到群消息与私聊转发）。

引入时的迁移方式：`HostEvent` 作为宿主层真源，`HostEvent.project() -> RuntimeInput`，
策略代码不改；`RuntimeInput` 退化（或保留）为决策视图。

## 多平台目标

已确认要接的平台：Telegram、微信、抖音、B站（外加现有 AstrBot/QQ 与 DSH）。
它们的差异主要在**会话形态**（频道/评论/私聊）与**发送能力**（能否语音/引用/撤回），
这两点分别由 `scene` / `conversation_id` 和后续的发送端口表达，不需要新的事件结构。
