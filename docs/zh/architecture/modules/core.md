# core：领域对象与纯策略

## 职责

core 定义记忆领域的稳定词汇和不依赖 IO 的决策。它不负责 SQL、缓存、模型、网络或 AstrBot 事件。

## 数据模型

- **Source**：冻结的数据对象，标识一条原始消息；make_source_id 根据宿主事件 ID 或会话、说话人、角色、时间和正文生成稳定 ID。校验要求有 ID、受支持的 role 和非空正文。
- **Artifact**：由 Header 与 family payload 构成。Header 包含 ID、family、revision、state、scope、lineage、strength、time、said_by、shareable 和 subject_id。
- **Lineage**：sources 是原始证据；derived_from 是形成该抽象结论的上游 Artifact。二者用途不同。
- **TimeSpan**：created、updated 与有效期字段由上层写入；抽取可用事件时间作为 created。查询有效期由 recall/temporal 执行。

family 与 memory level 是两个不同维度：

| family | 用途与 payload 入口 |
|---|---|
| memory | 有 text 与 fact、scene、detail、impression 四种 level；可包含 shape、chrono、about、tags 和行为证据字段 |
| persona | 当前人格文本及其 seed/Dream 来源元数据 |
| example | user/assistant 对话样例 |
| media | type、title、url，可带 summary/shared_by |
| secret | 带 ref 与 shadow_text 的受保护数据；召回管线排除该 family |
| designated | 带 text、trigger 与 given 的指定交付内容 |

family 校验器位于 core/families。make 只构造对象，不自动校验；生产调用方在提交前显式调用 validate。revise 保持 ID 与 family，增加 revision 并更新时间。

## 纯策略

- **strength.py** 计算留存率、衰减权重和 recall/spoken/confirmed 强化；显式 hits 优先，旧数据可从 weight 推算有效命中。
- **versioning.py** 校验新版本的稳定 ID/family、顺序连续性和 created 时间；定义状态事件及语义变化判定。
- **disclosure.py** 把会话亲和、主体匹配、scope prior、敏感度和相关度组合为 full、paraphrase、hint 或 silence。只有 full 可返回 Artifact 原文；较低等级使用固定通用文本。secret family 的敏感度令其不能披露。
- **graph.py / tree.py** 通过注入的仓储协议处理关系边和父子结构，不自行写 SQL。causal 边保留显式接口，没有自动语义推断。
- **capacity.py** 根据容量快照和可配置阈值，纯函数式地给出状态与调度动作；执行由 services 完成。
- **trace.py** 清理运行追踪字段并投影运行时间线，限制可保存的数据种类。

## 关键不变量

Source 是追加式事实；Artifact 是可修订解释。内容修订通过仓储的 expected_revision CAS 提交，不能以新对象覆盖旧 ID 的版本历史。subject_id、said_by、来源会话和 evidence 不可相互推断替代。payload 的结构由 family validator 维护。

实现入口：[artifact.py](../../../../core/artifact.py)、[source.py](../../../../core/source.py)、[disclosure.py](../../../../core/disclosure.py)、[versioning.py](../../../../core/versioning.py)。
