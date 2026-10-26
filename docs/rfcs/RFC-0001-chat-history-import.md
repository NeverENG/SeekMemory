# RFC-0001：QCE → ChatLab → SeekMemory 私聊历史初始化

- 状态：已接受，实施中（上传上限待代表性样本校准）
- 关联：[#76](https://github.com/NeverENG/SeekMemory/issues/76)

## 1. 目标与范围

本功能只用于初始化 SeekMemory：管理员导入已有的 Bot 私聊记录，沉淀 Bot 自身人格证据，以及 Bot 与该用户之间的互动记忆。

一次上传只包含一个 Bot 与一个用户的私聊。群聊、定期同步、日常补录、Bot 用户自助上传和多文件批量上传不属于首版范围。长记录可按时间范围拆成多份，针对同一目标 UMO 逐份上传。

导入产生两类信息：

- **共享 Bot 人格**：从 Bot 一侧的回复和行为证据更新 `bot:self`。不根据用户发言生成人格画像。证据不足时不更新人格。
- **用户互动记忆**：只归属于该文件对应的目标用户 UMO，不能混入其他用户的记忆。

人格沿用现有证据门槛：需要真实用户消息与助手回复配对、至少 3 条不同的助手 Source，且置信度不低于 0.9。

输入链路为 QCE → ChatLab → SeekMemory。本 RFC 从 ChatLab 标准文件开始，不设计 QQ 登录、取数或 QCE 转换流程，也不定义完整字段到内部 DTO 的映射或新提取提示词。

## 2. 管理员使用流程

1. 管理员从 QCE → ChatLab 流程取得 ChatLab JSON 或 JSONL 文件。
2. 管理员在 AstrBot 宿主认证的 SeekMemory 管理界面上传文件。
3. 管理员选择 Bot 平台/账号和目标用户 ID，核对最终私聊 UMO。
4. SeekMemory 校验文件并展示预览；管理员确认后创建后台初始化任务。
5. 管理员可离开页面，之后查看任务进度、结果和有限错误摘要。

首版面向普通管理员的入口是 AstrBot 插件管理界面，不要求 SeekMemory 连接 ChatLab 或访问用户电脑上的 ChatLab API。CLI 可作为工程或运维入口，但不是普通用户的正式入口；QQ 附件上传不在首版范围内。

## 3. 输入文件与 Source 约束

### 3.1 格式与会话角色

首版只接受 ChatLab v0.0.2 的 JSON/JSONL 文件。其他版本整份拒绝，待适配并验证后再显式加入。

文件的 `meta.type` 必须为 `private`，且内容只能映射到一个 Bot 和一个目标用户。ChatLab 消息的 `sender` 引用成员的 `platformId`；可选的 `meta.ownerId` 不能单独证明哪一方是 Bot。系统先用管理员选定的 Bot 账号 ID 和目标用户 ID 精确匹配成员；无法无歧义匹配时，在预览中要求管理员明确选择 Bot 成员和用户成员。仍有歧义、无法映射到这两方或出现额外发言者时拒绝继续，不根据昵称猜测。相关字段按[ChatLab 标准格式](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)解析。

管理员确认的 Bot/用户成员 ID 必须与对应平台账号 ID 相同；目标私聊 UMO 中的用户 ID 也必须与已确认的目标成员 ID 相同，避免把正确解析的消息写入另一个用户范围。

管理员确认的目标私聊 UMO 是 Source 的会话范围。ChatLab 会话名称或元数据不能单独决定记忆归属。

### 3.2 稳定身份与幂等

#76 要求 Source 身份由格式 ID、canonical conversation ID 和外部消息 ID 构成。首版使用：

`(format_id, canonical_conversation_id, external_message_id)`

- `format_id` 固定为 `chatlab`，JSON 与 JSONL 共用。
- `canonical_conversation_id` 是管理员确认后的目标私聊 UMO。
- `external_message_id` 来自 ChatLab 的 `platformMessageId`；ChatLab 标准允许省略该字段，但 SeekMemory 首版要求每条可解析消息都有该 ID，因此 QCE → ChatLab 转换必须保留 QQ 原始消息 ID。
- ChatLab 的 `replyToMessageId` 若存在，映射到 `Source.reply_to`。人格证据只统计可验证的用户消息/助手回复配对；没有回复关系的消息仍可参与用户互动记忆提取，但不能作为人格配对证据。
- 每条可解析消息都必须有 `platformMessageId`。缺失任意一个稳定 ID，整份文件在正式导入前拒绝；不使用正文指纹或文件行号替代。
- Source ID 由身份元组的无歧义编码计算 SHA-256。导入使用独立 ID helper，不改变实时消息 `make_source_id()` 的语义。
- 同一 ID 且 Source 不可变字段完全相同，计为重复并跳过；同一 ID 对应不同字段，视为身份冲突并拒绝，不覆盖已有 Source。

相同消息重试、重叠时间范围和 JSON/JSONL 转换都按同一身份规则幂等。

### 3.3 校验、预览与坏行

正式导入前预览文件名、大小、格式、会话元数据、时间范围、消息数、发言者数、重复数、跳过数和校验警告。默认不展示正文；管理员主动展开后可以查看少量样例，样例不进入日志。确认目标 UMO 前不得开始处理。

| 错误类别 | 处理方式 | 示例 |
|---|---|---|
| 文件级错误 | 整份拒绝，正式导入写入为零 | 不支持的格式/版本、整体 JSON 无法解析、JSONL header 错误、无法绑定到一个目标会话、超过上限 |
| 身份错误 | 整份拒绝，正式导入写入为零 | 可解析消息缺少稳定 ID；同一 ID 对应不同 Source 字段 |
| 可安全隔离的消息错误 | 预览计数并列出行号；管理员确认后跳过 | JSONL 单行语法错误；有 ID 但缺少有效时间、发送者或可接纳内容 |

管理员确认含坏行的文件时，确认文案说明跳过行数；最终结果标记为部分导入。无法解析文件边界、发现身份冲突或有可解析消息缺少稳定 ID 时，不开始正式导入。

### 3.4 初始上传上限

以下是 SeekMemory 的临时安全上限，不是 ChatLab 格式限制。取得代表性 QCE → ChatLab 私聊样本后校准。

| 格式 | 文件大小上限 | 消息条数上限 | 解析方式 |
|---|---:|---:|---|
| ChatLab JSON | 20 MiB | 100,000 | 整体解析 |
| ChatLab JSONL | 512 MiB | 2,000,000 | 流式逐行解析 |

全实例暂存空间初始上限为 1 GiB。上传端按实际接收字节计数，不只信任 Content-Length；达到上限即拒绝并删除未完成文件。反向代理和 AstrBot 宿主也必须允许相应请求大小。空间不足时先清理过期文件，再拒绝新上传并提示管理员。

## 4. 权限、隐私与任务生命周期

### 权限和隐私

- 只有 AstrBot 实例管理员可以发起导入。
- 上传、预览、样例查看、确认、状态查询、重试、取消和提前放弃等接口均在服务端校验管理员身份；不信任请求参数中的用户名或随机 task ID。
- 入口复用 AstrBot 插件视图和插件 Web API，不另开监听端口；远程访问使用 HTTPS。
- 原始文件写入插件私有暂存目录，路径和文件名由服务端生成，不经静态路由公开；不接收压缩包。
- 日志、任务状态和错误摘要不包含聊天正文、密钥或凭据。样例消息仅在管理员主动展开预览时返回。

### 文件和任务保留

- 待管理员确认的预览文件最多保留 1 小时。
- 任务成功、取消或上传校验失败后立即删除原文件；正式处理失败时，原文件最多保留 24 小时供管理员重试，之后自动删除。
- 管理员确认后创建持久化后台任务。AstrBot 重启时，运行中的任务标为“中断”；首版由管理员从头重试，不做解析游标的自动续跑。稳定 Source ID 用于避免重复写入 Source。
- 每个任务通过 task–Source 关联记录本次包含的 Source。任务复用现有 `extraction_state`：`pending`、`retrying`、`deferred` 计为待提取，`extracted` 计为已提取，`dead` 计为失败；同一 Source 可以关联多个任务。
- 为支持 AstrBot 重启后的显式重试，活动任务和保留原文件的失败任务在私有任务表中暂存管理员确认的角色映射及目标 UMO；任务摘要 API 不返回这些字段。文件过期、任务放弃或任务无需重试时清除映射。
- 全部关联 Source 进入终态且人格更新结束后，固化阶段、计数和错误类型摘要，并删除逐 Source 关联。摘要保留 30 天后删除，不保存聊天正文。

## 5. 初始化处理方式

1. 校验文件、角色映射和目标 UMO；把所有可接纳消息按稳定 ID 保存为不可变 Source。
2. 所有有效话题都进入提取，不做本地重要性预筛。这不保证每个话题都会产出 Artifact。初始化任务须走非 triage 的提取路径；现有 Dream 批处理会按重要性筛选话题，不能用它处理这批历史。
3. 历史消息按事件时间稳定排序；时间相同则保留文件顺序。复用现有话题规则：相邻消息间隔超过 90 分钟，或 bigram Dice 相似度低于 0.12 时开启新话题；能通过 `reply_to` 找到父用户消息时，助手回复继承父话题。话题超过 120 条时切块，并尽量让直接问答留在同一块。稀疏历史可能被切得较碎。
4. 复用现有提取、证据校验和 Artifact 写入能力。Source 是不可变原始事实；Artifact 是可修订解释，生产写入必须经 `ArtifactStore.commit()`，保留版本、证据链接和 ledger。
5. 每份文件的所有话题处理结束后，基于截至目前累计的合格 Bot 行为证据增量更新共享 `bot:self`。用户互动记忆仍绑定目标 UMO。证据未过现有人格门槛时不更新人格。
6. 全部话题提取和人格更新结束后，任务进入终态。耗尽重试次数的话题标记为部分完成；仍用成功话题中的合格证据更新人格。

初始化任务使用现有 `extraction_state` / 全局提取队列，并用 task–Source 关联展示逐次导入进度。单次提取的批次上限只控制每轮处理量，未处理话题必须留在队列中继续处理；模型不可用或可重试失败时任务保持待处理/重试状态，不得提前报完成。不要为每次导入调用 `MaintenanceService.weekly()`，避免对全实例记忆执行维护。

首版不加入此前讨论过的实时 4:1 加权调度。初始化期间是否开放 Bot 常态服务、服务启停或流量门控不属于本 RFC 范围；若未来要求实时提取和初始化并行，再单独设计调度。

## 6. 与 issue #76 的关系

本设计通过 `(format_id, canonical_conversation_id, external_message_id)` 满足 #76 的稳定 ID 和重复导入要求。稳定消息 ID 是首版输入硬要求，因此 QCE → ChatLab 转换必须保留 QQ 原始消息 ID。

RFC 的产品选择与 #76 原描述存在差异：issue 目前写的是 CLI 优先、WebUI 后续、默认本地处理，并把持久化导入任务列为非目标；本 RFC 已确定管理员 WebUI 上传和持久化后台任务。实现前应按本 RFC 更新 #76 的阶段计划、入口和验收标准。

## 7. 待样本校准

代表性 QCE → ChatLab 私聊导出样本尚未放入仓库。取得样本后校准 JSON、JSONL 和暂存空间上限，并检查消息 ID、角色映射和时间戳是否符合本 RFC 的硬要求。

ChatLab 官方文档当前标注 v0.0.2，并说明规范仍在早期制定；其格式说明建议百万级记录使用 JSONL，支持 GB 级文件，头像也可使用内嵌 Data URL。因此，SeekMemory 的临时上限需要结合实际导出文件验证，不能只按消息数推算。[ChatLab 标准格式](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)。

## 8. 实施后的真实链路验证

功能实现后，启动 SeekMemory 并在本地或真实 AstrBot 容器/忠实 staging 环境中完成端到端 API 验证。测试使用 Lead 届时提供的非生产 API 访问方式和代表性 QCE → ChatLab 私聊记录。

至少验证管理员鉴权、上传、预览、确认、后台任务进度与终态、Source 稳定 ID 幂等，以及记忆/persona 的目标范围。记录运行环境、执行步骤、API 状态码和不含正文的请求/响应摘要、任务状态变化与计数，并核对持久化结果。验证结果写入实现对应的 `docs/issues/PR-XXXX.md`。

测试证据不得包含聊天正文、凭据或可识别用户的原始标识；日志和 PR 材料只保留脱敏后的状态、计数及必要的哈希标识。生产环境不作为默认验证目标，任何生产访问或修改仍遵守 Lead 授权要求。API 凭据不写入 RFC、仓库或测试记录。

## 9. 参考资料

- [ChatLab 标准格式](https://github.com/ChatLab/ChatLab/blob/main/docs/cn/standard/chatlab-format.md)
- [ChatLab API 文档](https://github.com/ChatLab/ChatLab/blob/main/docs/en/standard/chatlab-api.md)
- [AstrBot 插件视图文档](https://github.com/AstrBotDevs/AstrBot/blob/master/docs/en/dev/star/guides/plugin-pages.md)
