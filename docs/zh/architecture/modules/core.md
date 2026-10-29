# core：领域对象与纯策略

## 职责

core 定义记忆领域的稳定词汇和不依赖 IO 的决策。它不负责 SQL、缓存、模型、网络或 AstrBot 事件。

集中入口也导出上游已有的人格包/插画校验、格式标识及大小限额（`normalize_pack`、`validate_artwork` 等），不改变这些纯校验实现。

## 领域能力与外部依赖入口

本模块将对外提供的能力和要求外部提供的能力分开，两个入口只包含显式导出或协议声明，配有中英混合行为说明，不实现业务：

- **对外提供 — [`core/domain.py`](../../../../core/domain.py)**：领域类型，以及记忆构造/修订/校验、消息编号、版本检查、强度、披露、图、容量、人格、关系/互动和追踪整理能力。函数与类型直接沿用原对象，完整调用参数可由原定义或 `inspect.signature()` 查看；没有包装函数或空实现。
- **要求外部提供 — [`core/ports.py`](../../../../core/ports.py)**：`GraphArtifactStore` 的连接读写。每个方法说明返回值、读写影响和必要的失败约定；实现由外部注入，连接生命周期也由外部管理。

调用方使用 `from core.domain import make, Graph` 获取领域能力，使用 `from core.ports import GraphArtifactStore` 获取依赖声明；插件包中使用相应的相对导入。`core.artifact`、`core.graph` 等领域实现入口继续有效，`core.graph.GraphArtifactStore` 是端口声明的同一对象。图实现直接引用 `ports.py`，`domain.py` 正常导出图类型，不再需要延迟绑定。原内部 `core.interfaces` 入口已移除。

树的完整读写协调由 [TreeService](services.md) 负责，内部入口为 `from services import TreeService`；原 `core.tree` 及 core 的树相关导出已移除。树所需的 `TreeArtifactStore`、`TreeCache` 声明位于 `app/ports.py`，core 不反向引用应用层或服务层。

`make`/`revise` 仍读取系统时间，`load_thresholds` 仍读取环境变量。`Graph` 通过注入对象读写连接；`edges_of` 查询连接两端但不返回原方向。

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
| relationship | 按 subject 版本化保存 affinity、confidence、证据数、迟滞档位和无正文 policy snapshot；不进入 Recall |

family 校验器位于 core/families。make 只构造对象，不自动校验；生产调用方在提交前显式调用 validate。revise 保持 ID 与 family，增加 revision 并更新时间。

## 纯策略

- **strength.py** 计算留存率、衰减权重和 recall/spoken/confirmed 强化；显式 hits 优先，旧数据可从 weight 推算有效命中。
- **versioning.py** 校验新版本的稳定 ID/family、顺序连续性和 created 时间；定义状态事件及语义变化判定。
- **disclosure.py** 把会话亲和、主体匹配、scope prior、敏感度和相关度组合为 full、paraphrase、hint 或 silence。只有 full 可返回 Artifact 原文；较低等级使用固定通用文本。secret family 的敏感度令其不能披露。
- **graph.py** 通过注入的仓储协议处理关系边，不自行写 SQL。causal 边保留显式接口，没有自动语义推断。
- **capacity.py** 根据容量快照和可配置阈值，纯函数式地给出状态与调度动作；执行由 services 完成。
- **trace.py** 清理运行追踪字段并投影运行时间线，限制可保存的数据种类。
- **relationship.py / relationship_rules.py** 管理稳定关系 ID、快照、迟滞、十类 reason 证据规则、scope 权重、同轮上限和有界 revision plan。模型只分类观察，不能写 affinity、delta、band 或 policy version。
- **interaction_policy.py** 纯函数地产生稳定回复概率、固定语气、亲昵称呼/follow-up/关心/玩笑权限和未来 proactive kind 权限。采样按不可变 Source ID 稳定；ID 缺失时 fail open。

## 常量与策略参数归属

常量随所属规则维护，不设全局常量文件。相同数值不一定表达相同含义，例如关系置信度门槛和亲近档位门槛分别维护。

| 类别 | 唯一归属与使用方式 |
|---|---|
| 算法内部参数 | 遗忘的情绪系数、显著度范围及命中系数在 `strength.py`；披露的阈值与因子在 `disclosure.py`；关系进出档位阈值在 `relationship.py`；置信度平滑参数在 `relationship_rules.py`。具名参数放在文件顶部，新增内部名称不从 `domain.py` 导出，也不成为用户配置。 |
| 已有可配置策略值 | `CapacityThresholds`、`RelationshipScoringPolicy`、`InteractionPolicySettings` 分别保留本领域的参数与默认值。互动固定规则表复用 `InteractionPolicySettings` 的默认概率；其他层的配置解析与默认值整理不属于 core 常量归属范围。 |
| 数据约定 | 记忆类别、消息角色、操作名称及人格来源继续留在各自领域；关系档位及策略版本由 `relationship.py` 定义，family 校验器直接引用；追踪中的披露合法值由 `DisclosureLevel` 派生。持久化值和顺序不变。 |
| 校验与诊断限制 | 人格文件长度限制留在 `persona.py`，自我印象信任要求留在 `bot_behavior.py`，追踪数量上限和白名单留在 `trace.py`。 |

已有对外常量保留原导出。整理归属不改变数值、比较边界、运算顺序、配置读取时机或算法结果。

## 关键不变量

Source 是追加式事实；Artifact 是可修订解释。内容修订通过仓储的 expected_revision CAS 提交，不能以新对象覆盖旧 ID 的版本历史。subject_id、said_by、来源会话和 evidence 不可相互推断替代。payload 的结构由 family validator 维护。

实现入口：[artifact.py](../../../../core/artifact.py)、[source.py](../../../../core/source.py)、[disclosure.py](../../../../core/disclosure.py)、[versioning.py](../../../../core/versioning.py)。

<a id="core-verification"></a>

## 验证入口与证据范围

以下是现有测试的查找入口，不是逐个导出名称的完整覆盖证明。测试文件可能同时验证多个模块；当前分层由 [tests/layers.py](../../../../tests/layers.py) 按文件名确定，不能把 `unit` 层等同于“只测 core”或“完全不访问数据库”。

| 能力 | 当前测试入口 | 验证内容与限制 |
|---|---|---|
| 领域入口与外部依赖声明 | [test_core_interface_contract.py](../../../../tests/test_core_interface_contract.py) | 导出对象身份、声明不含业务实现、端口调用参数、依赖方向及不同导入顺序；不证明每个导出操作的业务行为均被覆盖。 |
| Artifact 构造、修订和类别校验 | [test_artifact.py](../../../../tests/test_artifact.py) | 必填字段、默认值、文本读取及修订不改原对象；不验证数据库事务。 |
| Source、版本与提交 | [test_kernel.py](../../../../tests/test_kernel.py) | 消息编号、版本检查及仓储提交等；同文件含纯规则、SQLite 和其他模块场景。 |
| 留存、衰减和强化 | [test_strength.py](../../../../tests/test_strength.py)、[test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py) | 留存随时间变化、情绪阈值、强化增量与冷却；不证明真实对话中的长期记忆效果。 |
| 披露与隐私输出 | [test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py)、[test_kernel.py](../../../../tests/test_kernel.py)、[test_privacy_outputs.py](../../../../tests/test_privacy_outputs.py) | 阈值边界、跨会话披露及最终上下文的受保护内容检查；最终输出检查跨越 core 与召回模块。 |
| 图连接 | [test_link.py](../../../../tests/test_link.py) | 显式因果连接、度数及联想流程；当前测试借助 SQLite 和缓存，不是独立的纯图规则测试。 |
| 容量决策 | [test_capacity.py](../../../../tests/test_capacity.py) | 压力状态、调度动作和配置覆盖；同文件还包含队列、存储和恢复流程。 |
| 人格与自我印象可信条件 | [test_persona.py](../../../../tests/test_persona.py)、[test_persona_bootstrap.py](../../../../tests/test_persona_bootstrap.py)、[test_self_impression.py](../../../../tests/test_self_impression.py) | 人格初始化、证据约束及维护后的可信结果；含跨模块流程，不代表真实模型会形成恰当人格。 |
| 关系与互动规则 | [test_relationship.py](../../../../tests/test_relationship.py)、[test_relationship_runtime.py](../../../../tests/test_relationship_runtime.py)、[test_core_policy_contract.py](../../../../tests/test_core_policy_contract.py) | 证据评分、关系档位进出阈值、稳定采样和互动权限；也包含抽取、维护和适配器场景。 |
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
python tests/test_kernel.py
python tests/test_e2e_kernel.py
python tests/test_privacy_outputs.py
```

这些命令不是所有 core 改动的固定最小集合，也不替代上表中对应能力的检查。全仓分层命令与选择原则见[开发环境与验证](../../guides/development.md)。测试通过只说明已执行的场景符合断言；不等同于真实模型抽取质量、真实 AstrBot 宿主验收或记忆效果提升。

## 跑分如何用于 core 验证

目前没有覆盖全部 core 能力的独立综合跑分。现有[跑分入口](../../../../benchmarks/README.md)主要组合 core、召回和存储模块，结果需按测量内容解释：

- `benchmarks/dataset.py` 调用实际 `retention` 计算合成样本的留存率；`run.py` 的强化数字则比较预先按提及次数设置的权重，没有执行实际 `reinforce`。它不能验证强化逻辑是否正确。
- `run.py` 的旧“综合像人指数”是自定义加权分数；无期望答案的查询不计入命中率，生成报告也没有质量退化的失败门槛。不能以高分或脚本成功作为记忆增强的验收。
- 所谓 token 压缩比实际使用字数，不能当作模型 token 数或费用；耗时依赖运行机器，日期和编号仍受系统时钟影响。
- `benchmarks/bm25.py` 有独立冻结验收，验证其规定数据和参数下的检索结果；不覆盖所有 core 规则，也不替代完整披露和隐私检查。

比较前后版本时，应记录提交、数据集、配置、运行命令和具体指标，区分算法行为、检索效果与性能。测试和跑分入口均不替代真实模型或宿主验收。
