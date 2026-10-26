# 架构总览

## 设计对象

SeekMemory 将原始对话和对话结论分开保存：

- **Source** 是不可变的原始消息，保留消息 ID、会话、说话人、角色、时间、回复关系和正文。
- **Artifact** 是可修订的派生结论，按 family 保存 payload，并通过 lineage 指向证据 Source 和上游 Artifact。
- Artifact 每次修订保留稳定 ID，revision 逐次增加。数据库同时保存当前节点、版本快照、版本级证据和账本记录。

三个字段不能混用：subject_id 表示结论关于谁，said_by 表示当前结论由谁产生，lineage.sources 表示支持结论的原始消息。Source 的 session_id 表示来源会话。

## 运行分层

    AstrBot 事件与插件生命周期
      → adapters/：把宿主事件转换为端口调用并提供宿主能力
      → services/：编排访问、抽取、召回、维护、容量与管理用例
      → app/：跨模块 DTO、端口、预算和运行时策略
      → core/：Source、Artifact、版本、披露、关系和容量等领域原语
      ↔ perceive/、recall/、maintain/：抽取、读取和维护策略
      ↔ store/：SQLite 仓储、缓存与持久化边界
      → webui/ + dashboard/：管理 API、宿主桥接和前端

依赖方向由代码边界保护：core 不依赖宿主或存储；SQL 由 store 管理；AstrBot 类型留在 adapters 与 webui 宿主路由；服务层组合业务模块，不实现 SQL。

## 写入路径

1. AstrBot hook 将消息和会话身份交给 AccessService 与 AgentRuntime。可观察的用户消息由 RunRecorder 建立不可变 Source，并进入 Source-backed extraction_state 队列。助手回复在模型响应回调中也被记录为 Source，保留实际 reply_to。
2. Buffer 为 pending Source 建立 DialogueTurn 视图，并按会话和话题分组。回复若引用已处理的用户消息，可只读找回父 Source 作为配对上下文，不会重新排队。
3. IngestService 选择话题和 provider；Dream 路径可先做确定性重要性筛选。模型输出由 perceive 转成纯 ExtractionPlan：解析 JSON、校验证据、按主体和 scope 去重，构造并验证 Artifact。
4. IngestService 对每个生产 Artifact 使用 expected_revision 提交。Artifact head、版本、版本级证据、state event 和账本在同一个 SQLite 事务内写入；成功后才更新 Cache，并尝试建立关系边。
5. 抽取失败会保留队列行并记录有限错误类型、重试时间和次数。Source 不因抽取成功或失败被删除。

## 召回路径

1. 宿主请求 hook 先通过 AccessService。运行时上下文适配器调用 RecallService，后者复用唯一的 recall pipeline。
2. Pipeline 从 Cache 取 active Artifact，过滤 family secret 和不属于当前查看者的 designated；普通 memory 的 private、shared、shadow 都可进入候选池。这里的 scope 不构成普通 memory 的硬会话可见性门。
3. 纯时间、寒暄等非记忆意图不启动通常检索。其他查询由 GraphRetriever 或 HybridRetriever 计算候选，再按相关性证据闸门、排序和预算选取。HybridRetriever 结合图激活与本地 BM25 字面信号，不调用模型或网络。
4. 当召回不足且查询有记忆意图时，系统可读取有时间和数量上限的近期 Source；Source 只用于按 ID 查找仍 active 且有当前版本证据的 Artifact。Source 正文不会出现在提示词、诊断摘要、日志或组装块中。
5. 候选经过统一披露后才组装。披露综合当前会话、主体、scope、敏感度和查询相关性，结果为全文、固定改述、固定提示或静默。designated 另需私聊、触发词匹配且尚未交付。
6. 组装器按 persona、impression、scene/detail/fact 等层级安排内容，并返回真正进入最终块的 Artifact IDs。请求成功后才为实际注入的记忆排队强化。

## 数据与副作用边界

- 一个 Store 拥有一个 SQLite 连接；仓储共享该连接，以便 Artifact 事务和 Source 入队事务有明确原子边界。
- Cache 是 active Artifact 的派生读模型。Cache.version 用于通知 BM25 等派生索引重建，不代替数据库事实。
- runtime_state 是可变的会话调度状态；runtime_episodes 是追加式运行审计。两者都不是 Source 或 Artifact。
- lifecycle Journal、容量 Trace 与 Agent Run Trace 分别服务不同诊断场景。Run Trace 是有界、字段白名单约束的诊断记录，不是业务账本。
- 记忆异常和诊断存储失败不应阻断普通聊天；不完整输入不会被静默标记为抽取成功。

## 当前实现边界

本架构描述仓库当前实现，不表示未接入的提案。检索使用图激活和可选 BM25；没有本地向量检索。maintain/reflect.py 提供纯规则信号，但目前没有生产调用方。Agent Runtime 的运行时门默认关闭；启用后可调度 ambient 延迟回复，但该路径不运行完整 AstrBot 工具循环。详情见各[模块设计](modules/core.md)。
