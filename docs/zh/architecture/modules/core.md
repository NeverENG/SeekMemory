# core：领域对象与纯策略

## 职责

core 定义记忆领域的稳定词汇和不依赖 IO 的决策。它不负责 SQL、缓存、模型、网络或 AstrBot 事件。

集中入口也导出上游已有的人格包/插画校验、格式标识及大小限额（`normalize_pack`、`validate_artwork` 等），不改变这些纯校验实现。

## 领域能力与外部依赖入口

本模块将对外提供的能力和要求外部提供的能力分开，两个入口只包含显式导出或协议声明，配有中英混合行为说明，不实现业务：

- **对外提供 — [`core/domain/`](../../../../core/domain/)**：领域类型，以及记忆构造/修订/校验、消息编号、版本检查、强度、披露、图、容量、人格、关系/互动和追踪整理能力。函数与类型直接沿用原对象，完整调用参数可由原定义或 `inspect.signature()` 查看；没有包装函数或空实现。
- **要求外部提供 — [`core/port/`](../../../../core/port/)**：`GraphArtifactStore` 的连接读写及 `TreeEdgeReader` 的树连接只读能力。每个方法说明返回值、读写影响和必要的失败约定；实现由外部注入，连接生命周期也由外部管理。

调用方使用 `from core.domain import make, Graph` 获取领域能力，使用 `from core.port import GraphArtifactStore` 获取依赖声明；插件包中使用相应的相对导入。领域实现按能力收在 `core/domain/`，图存储协议在 `core/port/graph.py`；`core.artifact`、`core.graph` 和 `core.ports` 等旧路径由 `core/_legacy.py` 注册为兼容别名，不再保留根目录转发文件，`core.graph.GraphArtifactStore` 与新端口为同一对象。目录入口只导出能力，不承担业务实现；新代码优先导入所属的领域文件或 `core.port`。原内部 `core.interfaces` 入口已移除。

树的完整读写协调由 [TreeService](services.md) 负责，内部入口为 `from services import TreeService`；原 `core.tree` 及 core 的树相关导出已移除。树所需的 `TreeArtifactStore`、`TreeCache` 声明位于 `app/ports.py`，core 不反向引用应用层或服务层。

`make`/`revise` 仍读取系统时间，`load_thresholds` 仍读取环境变量。`Graph` 通过注入对象读写连接；`edges_of` 查询连接两端但不返回原方向。

模型调用不属于 `core.port`：抽取模型协议由 `app.ports.ChatModel` 持有，运行时文本协议由 `app.runtime.contracts.ModelGateway` 持有，AstrBot 提供方在边缘适配。目录迁移不改变模型选择或调用行为。

`core/domain/memory/tree.py` 经有向 `tree_child:<父节点 ID>` 边返回多个父节点；祖先广度查询分别限制深度、单节点父数和访问总数，并去重截环。`TreeService` 接收多个父节点 ID，验证身份与状态，在 Artifact 提交后仅写树边。既有单值 `nodes.parent` 列仍留在数据库结构中，但不再读写为树关系；不自动迁移，旧库若存在只有父字段而没有树边的关系，启用树查询时回退到平面召回。

领域实现现在按 `core/domain/memory/`（证据、版本、检索与披露）、`character/`（人格）、`social/`（关系与互动）、`operations/`（容量与追踪）分组；`core/families/` 保持 payload 校验归属，`core/port/` 仅声明领域实际依赖的图存储协议。`core.domain` 继续集中导出稳定 API；旧 `core.<module>` 与 `core.domain.<module>` 路径指向同一实现模块，不重复维护规则。应用运行时的契约继续留在 `app/runtime/contracts/`，不搬入记忆领域的端口。

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
| relationship | 按 subject 版本化保存熟悉、信任、温度、张力、稳定性和置信度；V2 观察期不进入 Recall，也不决定回复 |

family 校验器位于 core/families。make 只构造对象，不自动校验；生产调用方在提交前显式调用 validate。revise 保持 ID 与 family，增加 revision 并更新时间。

## 纯策略

- **strength.py** 计算留存率、衰减权重和 recall/spoken/confirmed 强化；显式 hits 优先，旧数据可从 weight 推算有效命中。
- **versioning.py** 校验新版本的稳定 ID/family、顺序连续性和 created 时间；定义状态事件及语义变化判定。
- **disclosure.py** 把会话亲和、主体匹配、scope prior、敏感度和相关度组合为 full、paraphrase、hint 或 silence。只有 full 可返回 Artifact 原文；较低等级使用固定通用文本。secret family 的敏感度令其不能披露。
- **graph.py** 通过注入的仓储协议处理关系边，不自行写 SQL。causal 边保留显式接口，没有自动语义推断。
- **capacity.py** 根据容量快照和可配置阈值，纯函数式地给出状态与调度动作；执行由 services 完成。
- **trace.py** 清理运行追踪字段并投影运行时间线，限制可保存的数据种类。
- **relationship.py / relationship_rules.py** 定义稳定关系 ID、十类候选和多维快照。只有同 subject、带时区且已复核的 Source 事件参与回放：私聊权重 1.0、群聊 0.5，轻/强事件系数 1/2，学习率 0.25。熟悉度按 180 天、置信度与稳定性按 90 天衰减；温度与信任分别按 45/180 天半衰期，经 `tanh` 限幅；张力在 24 小时冷却后按 14 天半衰，只有绑定更早已核验负向事件的修复才能减轻对应张力，上限 75%，不重复扣减。同 Source 不重复计分；模型只提议候选和语义判断，不写维度或分数。
- V2 不产生单一“好感度总分”。观察期即使配置 `enforce` 也不按关系状态改变回复或语气；Runtime 自身的门控独立。

## 常量与策略参数归属

常量随所属规则维护；关系 V2 的证据权重、半衰期和冷却参数与记忆披露阈值相互独立。

| 类别 | 唯一归属与使用方式 |
|---|---|
| 内部算法参数 | 情绪因子与显著性边界归 `strength.py`，披露阈值归 `disclosure.py`，关系 V2 的证据影响、衰减及冷却归 `relationship_rules.py`。新增私有名称不会自动由 `domain.py` 导出或暴露为配置。 |
| 现有可配置策略值 | `CapacityThresholds` 与 `RelationshipScoringPolicy` 保留各自参数，关系配置由服务层规范化。V1 互动规则及关系回复门控已退役。 |
| 数据契约 | family 名称、Source 角色、操作名及人格来源保留各自领域归属。`relationship.py` 持有 V2 快照及策略标识；family 校验仍接受历史 V1 payload，但不将 affinity 提升为 V2。追踪从 `DisclosureLevel` 导出允许的披露值。 |
| 校验与诊断限制 | 人格文件长度限制留在 `persona.py`，自我印象信任要求留在 `bot_behavior.py`，追踪数量上限和白名单留在 `trace.py`。 |

无关的对外常量保持原导出。V2 移除 V1 档位和互动导出，不保留过时评分行为。

## 关键不变量

Source 是追加式事实；Artifact 是可修订解释。内容修订通过仓储的 expected_revision CAS 提交，不能以新对象覆盖旧 ID 的版本历史。subject_id、said_by、来源会话和 evidence 不可相互推断替代。payload 的结构由 family validator 维护。

实现入口：[artifact.py](../../../../core/domain/memory/artifact.py)、[source.py](../../../../core/domain/memory/source.py)、[disclosure.py](../../../../core/domain/memory/disclosure.py)、[versioning.py](../../../../core/domain/memory/versioning.py)。

<a id="core-verification"></a>

## 验证入口与证据范围

以下是现有测试的查找入口，不是逐个导出名称的完整覆盖证明。纯规则和跨模块流程在独立文件中；当前分层由 [tests/layers.py](../../../../tests/layers.py) 按显式层级后缀优先、旧文件名回退确定。层名不是“只测 core”的保证；下面明确各能力的验证归属。

| 能力 | 当前测试入口 | 验证内容与限制 |
|---|---|---|
| 领域入口与外部依赖声明 | [test_core_interface_contract.py](../../../../tests/test_core_interface_contract.py) | 导出对象身份、声明不含业务实现、端口调用参数、依赖方向及不同导入顺序；不证明每个导出操作的业务行为均被覆盖。 |
| Artifact 构造、修订和类别校验 | [test_artifact.py](../../../../tests/test_artifact.py) | 必填字段、默认值、文本读取及修订不改原对象；不验证数据库事务。 |
| Source、版本与提交 | [test_kernel_integration.py](../../../../tests/test_kernel_integration.py) | [test_kernel_unit.py](../../../../tests/test_kernel_unit.py) 验证消息编号、版本及披露纯规则；集成文件验证 SQLite 原子提交、检查点与迁移。 |
| 留存、衰减和强化 | [test_strength.py](../../../../tests/test_strength.py)、[test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py) | 留存随时间变化、情绪阈值、强化增量与冷却；不证明真实对话中的长期记忆效果。 |
| 披露与隐私输出 | [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py)、[test_kernel_unit.py](../../../../tests/test_kernel_unit.py)、[test_privacy_outputs.py](../../../../tests/test_privacy_outputs.py) | 阈值边界、跨会话披露及最终上下文的受保护内容检查；最终输出检查跨越 core 与召回模块。 |
| 图连接 | [test_link_integration.py](../../../../tests/test_link_integration.py) | 显式因果连接、度数及联想流程；集成文件保留 SQLite、缓存和建联流程；[test_graph_unit.py](../../../../tests/test_graph_unit.py) 通过小型存储端口替身验证图规则。 |
| 容量决策 | [test_capacity_unit.py](../../../../tests/test_capacity_unit.py) | 压力状态、调度动作和配置覆盖；队列、存储及恢复位于 [test_capacity_integration.py](../../../../tests/test_capacity_integration.py)。 |
| 人格与自我印象可信条件 | [test_persona.py](../../../../tests/test_persona.py)、[test_persona_bootstrap.py](../../../../tests/test_persona_bootstrap.py)、[test_self_impression.py](../../../../tests/test_self_impression.py) | 人格初始化、证据约束及维护后的可信结果；含跨模块流程，不代表真实模型会形成恰当人格。 |
| 关系 V2 回放与核验 | [test_relationship_unit.py](../../../../tests/test_relationship_unit.py)、[test_relationship_integration.py](../../../../tests/test_relationship_integration.py)、[test_relationship_verifier.py](../../../../tests/test_relationship_verifier.py)、[test_store.py](../../../../tests/test_store.py) | 显式时钟回放、候选分离、语义核验和带 Source 证据的版本持久化；样本不代表真实模型误报率或真实 AstrBot 宿主验证。 |
| 运行追踪 | [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py)、[test_run_trace.py](../../../../tests/test_run_trace.py) | 披露词表、数量限制及追踪落盘后的正文排除与恢复；后者是追踪集成检查。 |

在仓库根目录定向执行接口及常见领域规则检查：

```bash
python tests/test_core_interface_contract.py
python tests/test_core_policy_contract.py
python tests/test_artifact.py
python tests/test_strength.py
```

涉及版本提交、披露或完整数据路径时，按改动补充相关检查：

```bash
python tests/test_kernel_integration.py
python tests/test_e2e_kernel.py
python tests/test_privacy_outputs.py
```

这些命令不是所有 core 改动的固定最小集合，也不替代上表中对应能力的检查。全仓分层命令与选择原则见[开发环境与验证](../../guides/development.md)。测试通过只说明已执行的场景符合断言；不等同于真实模型抽取质量、真实 AstrBot 宿主验收或记忆效果提升。

## 跑分如何用于 core 验证

[固定记忆回归](../../../../benchmarks/README.md)组合 core、召回及存储，不是覆盖全部 core 能力的独立跑分。`benchmarks/run.py` 使用固定样本、日期、编号及配置，逐题比较卫生前代码和目标代码；JSON 明确返回通过或失败，退化时命令非零。普通输出新增运行目录，不覆盖历史报告。

候选命中与最终上下文命中、无答案题误召回、包含无答案题的候选噪声及字数分别统计；完整管线检查隐私和正常披露正例。样本留存调用真实 retention，但没有执行夜间维护；样本权重比没有调用 reinforce，不能证明强化正确性。字数不是模型 token 数或费用，旧人格综合分仅保留为历史。

`benchmarks/bm25.py` 的冻结数据和门槛保持独立不变。报告记录代码、评测器、语料及环境，耗时只作环境相关描述。通过表示相对固定基线无退化，不等于没有既有误召回，更不替代真实模型或宿主验收。

人格包的明确应用关联和回退规则见 [WebUI](webui.md)。`core/domain/character/persona_application.py` 拥有规范内容、设定和图片摘要以及可选应用元数据的只读投影；不读写文件，不根据旧 seed ID 猜测关联。姓名、正文、风格或边界的变化与包资源变化分别比较。
