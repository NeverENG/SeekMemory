# perceive：对话缓冲与抽取

## 职责

perceive 把待处理对话转换为经过证据和 family 校验的候选 Artifact。提示词、解析、话题缓冲、重要性 triage 和模型适配在这里；生产数据库写入由 IngestService 拥有。

## 缓冲与话题

Buffer 是 Source-backed extraction queue 的内存视图。启用仓储时，入队同时持久化 immutable Source 与 extraction_state；内容不在队列表中重复保存。历史 pending.json 仅用于兼容迁移/无仓储支持路径。

话题在单个会话内构建：用户与实际回复通过 reply_to 配对，助手回复继承父消息话题；若父 Source 已处理，可读回作配对上下文，不会再次排队。没有回复关联时，超过 90 分钟的时间间隔或低于 0.12 的字符二元组 Dice 相似度会开始新话题。话题 TTL 是抽取触发信号，不是 Source 删除期限。

## 抽取管线

1. IngestService 选择 pending topic 或由 Dream triage 选择高价值 topic。
2. ProviderChatModel 把 ChatRequest 映射到宿主 provider；抽取 prompt 要求返回结构化 JSON 数组和可核对的来源 ID。
3. parse_response_checked 区分合法空数组与空响应/无效 JSON。失败可重试，不会被当作“没有记忆”。
4. build_plan 校验证据 ID，确定 subject_id、scope、event time、strength 和 family payload；在 subject/scope 边界内做字面去重，并校验 Artifact。
5. 对多话题同会话批次，模型输出必须给每条结论提供当前批次、单一话题内的证据。行为记忆还必须由实际 assistant Source 和其 user parent 组成有效配对。
6. ExtractionPlan 返回 Artifact 列表和跳过/错误信息。IngestService 使用 CAS commit、更新 Cache、修订重复 impression，并创建相似/时间关系。

主体规范化只作用于新抽取候选：对 `owner`、`speaker`、`third_party` 或未指定种类的精确 `user(id)` 标签，仅当候选自身引用的同会话用户 Source 的 speaker_id 确认为该 id 时，才去掉角色包装；省略引用的兼容事实只使用本次输入的 Source，不借用无关上下文。规范化在去重及构造前执行，payload 与 header 使用同一主体。未验证、嵌套、非用户标签和 self/world/relation 语义不改认 owner；无 Source 的旧输入不获得验证身份。提示词要求输出纯编号。

兼容策略为**只修后续抽取，保留旧数据**：不迁移或重写既有 Artifact、Source、版本或账本，不改 schema、配置键、披露阈值或召回读取逻辑。旧包装主体可能仍被降级披露，修订或重抽取须另行决定。回滚后新记录的纯编号仍可读取，但后续抽取可能再次保存包装标签。

## Dream triage 与恢复

importance.py 用规则对话题打分，优先身份、偏好、关系、计划、隐私边界、重要事件和用户纠正。Assistant 行为只在同话题有用户文本时参与评分；assistant-only 话题不会单独触发模型。该 triage 只用于 Dream，不改变普通 nightly/idle FIFO 话题选择。

pending 行在成功后标记 extracted；模型或提交路径失败则保留并按退避重试，超过次数后进入 dead 供管理排查。Source 一直保留作为原始证据。

## 接口与文件归属

`perceive/domain.py` 明确导出受支持入口；`perceive/ports.py` 复用 app 已有缓存、原始消息、抽取队列及模型协议，并声明旧提供方调用形式。旧实现路径和帮助函数别名继续可用；这些入口文件不包含业务实现。

| 文件 | 职责与副作用 | 逻辑复杂度及耦合 |
|---|---|---|
| `buffer.py` | 队列接纳、待处理视图、确认及旧文件协调 | 中至高：管理现有视图，借用仓储 |
| `buffer_policy.py` | 话题连续性、既有阈值及 ISO 解析 | 低：纯输入规则，无读写 |
| `buffer_codec.py` | 旧行转换及按原始消息编号对视图去重 | 低：纯转换 |
| `pending_file.py` | 旧 JSON 文件及读写错误状态 | 低至中：文件系统适配，不调用队列或模型 |
| `absorb.py` | 解析→证据校验→去重→构造 `ExtractionPlan` | 高：唯一纯计划所有者，仅查询缓存，不写记忆或调用模型 |
| `extraction_rules.py` | 既有主体、事件时间、强度和紧急程度计算 | 中：纯规则，时间和算法行为不变 |
| `dialogue_evidence.py` | 对话转换及精确不可变父消息读取 | 中：读取原始消息，不将父消息重新排队 |
| `extract.py` | 既有提示词构造及解析、去重兼容别名 | 低：不调用模型 |
| `response_parser.py`、`duplicate_policy.py` | JSON 恢复及身份范围内的字面去重规则 | 中：纯转换 |
| `behavior.py`、`relationship.py` | 证据、类别及关系观察校验 | 中：不修改分数或持久化 |
| `importance.py` | 确定性的夜间整理话题打分及排序 | 中：既有阈值和类别，无写入 |
| `model.py` | 兼容的 `ProviderChatModel` 提供方转接 | 低：外部调用、超时及取消，提供方由调用方管理 |
| `compress.py`、`calls.py` | 旧纯压缩帮助函数及有数量上限的无正文调用日志 | 兼容职责分别保留，压缩没有生产抽取调用方 |

提供方转接保留原路径，避免引擎→适配器→引擎的循环导入。提示词说明主体输出纯编号；证据配对、范围语义、评分数值及时间转换不变。`tests/test_perceive_interface_contract.py` 和全新的顶层及插件导入顺序检查保护接口；抽取、隐私、队列、话题及 HTTP 场景验证行为，不调用真实付费模型。

## 待处理发布与文件恢复

Buffer 在替换现有视图前准备全部队列行及其既有时间值。仓储读取或行转换失败时，保留原有消息及空闲标记。旧 JSON 先序列化到同目录临时文件，关闭后再原子替换；失败保留旧文件，并尽可能清理临时输出。JSON 布局和迁移身份不变。

旧文件模式的新增、取出、话题取出、恢复和确认，先保存拟发布视图再更新内存。保存失败时抛出 `OSError("pending_save_failed")`，暴露 `save_error` 并保留原有内存行；`save()` 仍明确返回布尔结果。队列确认失败时保留视图，重试仅消费原给定行，保留新输入及不可变原始消息。无原始消息编号的确认使用原行对象身份，因此新出现的相同行仍保留。这些保证适用于当前进程，不是新增持久任务系统。

`tests/test_perceive_failure_recovery.py` 覆盖五类操作的文件替换失败、失败或部分队列重载、无编号重复输入及队列确认重试。撤销恢复提交无需数据迁移。
