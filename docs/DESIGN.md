# Memory Agent · 规格 v2

> 一个让 QQ 机器人"像人一样记事"的 AstrBot 插件。
> 思想来源：[PowerContext](https://powercontext.oceanbase.io/zh/)（Source/Artifact/Dream/PreparedContext）+ git（内容寻址/版本链）。

---

## 0. 三条原则

> **记忆是神圣的（Source 不可改）**
> **结论是会错的（Artifact 可修）**
> **人格是沉淀的（Persona 会变）**

**第四条（抽象原则）**：

> **用属性组合描述记忆，不用类型枚举。**

加功能只加一个维度取值，不加一个分支。

---

## 1. 统一模型

**所有记忆都是同一个结构。**

```jsonc
{
  "id": "a_01",
  "content": "他加班到两点，我说陪他躺会儿",

  "about":  "other",       // self | other | relation | world
  "shape":  "point",       // point | span | pattern | rule
  "scope":  "private",     // private | shared | shadow
  "chrono": "once",        // once | periodic | annual

  "strength": {
    "weight": 1.2,         // 多容易想起
    "confidence": 1.0,     // 多可信
    "arousal": 0.6,        // 情绪强度
    "funny": 0.2           // 有趣度
  },

  "time": {
    "at": "2026-10-20T23:14",
    "valid_from": "2026-10-20",
    "valid_to": null,      // null = 仍生效
    "slot": null,          // periodic 用，如 "12:00"
    "tolerance": 0         // 分钟
  },

  "evidence": ["s_01"],    // 溯源：来自哪些 Source
  "links": [],             // 联想链
  "state": "active",       // active | forgotten | merged
  "hot_until": null,       // 防复读
  "hits": 0,
  "history": []
}
```

## 2. 四个维度

### `about` — 记的是谁

| 值 | 含义 | 注入影响 |
|---|---|---|
| `self` | 关于她自己 | 全量，短 |
| `other` | 关于对方 | 主预算 |
| `relation` | 关于我们 | 人称变「你们」 |
| `world` | 外部世界（媒体/知识） | 只给摘要 |

### `shape` — 什么形状（决定衰减）

| 值 | 含义 | 衰减 |
|---|---|---|
| `point` | 一次性事件 | 艾宾浩斯，情绪增强 |
| `span` | 一段时期 | 区间有效，过期失效 |
| `pattern` | 模式（他经常加班） | 极慢，几乎不衰减 |
| `rule` | 规律（他十二点吃饭） | 不衰减，时间窗加权 |

### `scope` — 谁能看见

| 值 | 含义 | 注入 |
|---|---|---|
| `private` | 只对当事人 | 全文 |
| `shared` | 共同经历 | 全文，人称「你们」 |
| `shadow` | 有这件事，内容不可见 | 只注入影子句 |

### `chrono` — 时间性

| 值 | 含义 | 加权 |
|---|---|---|
| `once` | 一次性 | 按新鲜度 |
| `periodic` | 周期（每天/每周） | 落在窗口 ×1.5 |
| `annual` | 每年一次（生日） | 当天 ×2.0 |

## 3. 记忆空间（旧类型 = 组合）

| 你要的东西 | about | shape | scope | chrono |
|---|---|---|---|---|
| 事实（名字/工作） | world | point | private | once |
| 发生过的事 | other | point | private | once |
| 作息规律 | other | rule | private | periodic |
| 生日 | other | point | private | annual |
| 共同经历 | relation | point | shared | once |
| 秘密影子 | other | point | shadow | once |
| 性格沉淀 | self | pattern | private | once |
| 犯错记录 | self | point | private | once |
| 媒体分享 | world | point | private | once |

**加新东西 = 选一组取值，不写新类。**

---

## 4. 生命周期

```
每轮     query → 召回 → 打分 → 裁剪 → 措辞
每晚     缓冲 → 沉淀 → 衰减 → 关系曲线
每周     合并 → 晋升 → 复盘
```

### 4.1 四层结构

```
工作记忆（当前对话）
   ↓
短期缓冲（今天，24h TTL，不注入）      ← 按话题单元存，不按消息
   ↓ 夜间整合
长期记忆（统一模型）
   ↓ 沉淀
人格（版本化）
```

**缓冲的必要性**：早上说"要辞职"，晚上说"算了"。早写进长期就记错了。

### 4.2 写入（门控）

```
每晚 23:50
  ① 读缓冲，按话题单元聚合
  ② 模型判断：0~3 条值得沉淀
  ③ 每条标四维 + strength
  ④ 去重（字面包含 / 字重比 > 0.75）
  ⑤ 写入，带 evidence
```

**反话检测**：短 + 语气词 + 字面矛盾 → `confidence = 0.4`，且**永不能覆盖已有记忆**。

### 4.3 衰减

```
留存率 R = e^(−t / S)
S = 基础 × (1 + 0.5 × 有效命中) × 形状系数 × 情绪系数
```

| 因素 | 取值 |
|---|---|
| 形状系数 | point 1.0 / span 1.2 / pattern 3.0 / rule ∞ |
| 情绪系数 | arousal > 0.7 → 1.5；< 0.3 → 0.8 |
| 首因 | 最早 3 条不衰减 |

**命中计数规则**：30 分钟内多次命中只计 1 次；跨天一天最多 1 次。

### 4.4 淘汰（五级）

| 级别 | 触发 | 动作 |
|---|---|---|
| 1 | `R < 0.3` | state = forgotten |
| 2 | active > 500 | 取最旧 50 条进整理 |
| 3 | 整理中相似 > 0.6 | 合并成 `pattern` |
| 4 | `hits > 10` | 晋升人格候选 |
| 5 | forgotten > 180 天 + 无引用 | 物理删 blob |

**稳态 ~800 条，每天进 3~5 出 3~5。**

### 4.5 双触发整理

| 触发 | 时机 | 范围 |
|---|---|---|
| 定期 | 每周日 23:50 | 全量六步 |
| 紧急 | active > 500 | 只合并最旧 50 条 |

**每周六步**：
```
1 缓冲沉淀 → 2 衰减计算 → 3 聚类合并
→ 4 晋升检查 → 5 关系曲线滑窗 → 6 反思复盘
```

### 4.6 强化（四来源）

| 来源 | 增量 |
|---|---|
| 被检索命中 | weight +0.1 |
| **她主动说出** | weight +0.3 |
| 对方确认（"对"） | weight +0.2 |
| 共同经历（shared） | 基础 ×1.5 |

### 4.7 情绪闭环

```
情绪低持续 2 天
  → 触发反思
  → 那段 episode 细节衰减 ×1.5（褪色）
  → 情绪标签保留
  → 新增 self：「我最近不太好」
```

---

## 5. 检索与组装

### 5.1 打分

```
score = 3.0 × 字面重合（二元组）
      + 2.0 × 标签匹配
      + 1.5 × 情绪匹配
      + 1.0 × weight
      + 0.5 × 新鲜度
      − 2.0 × 最近刚用过
      − 3.0 × hot
```

**梗维度**：消息含「咕咕嘎嘎/原神/鸣潮/抽象」→ 带梗标签 +2.0。

**探索**：90% 按分数取，10% 随机捞一条。

**联想**：命中 A → 沿 links 扩 1 跳，最多 2 条。

**会话缓存**：同会话内已注入的不再重复注入。

### 5.2 无语境回忆（random_recall）

```
无 query
按 funny × weight × 随机扰动 排序
排除 hot / sensitive
```

素材两个池：长期库（funny 高的）+ 当天缓冲。

### 5.3 组装（PreparedContext）

```
┌ 头部：常驻 ────────────────
│ ① 人格骨架            不可砍
│ ② 关系结论（1 句）    「他这三天话越来越少」
│ ③ 最相关记忆（≤3）
├ 中部：可丢 ────────────────
│ ④ 历史摘要（情绪优先）
│ ⑤ 其余记忆
│ ⑥ 语料（检索 top-8）
├ 尾部：高注意力 ────────────
│ ⑦ 最近 2 轮原文
│ ⑧ 本轮消息
└──────────────────────────
预算 2000 字，超了从 ⑥→⑤→④ 砍
```

**对抗 lost in the middle**：越影响"她是谁"越靠上，越影响"这次怎么回"越靠下。

### 5.4 时间注入

```
❌ Current datetime: 2026-10-21 12:03 (CST)
✅ 现在是周三中午
```

只给时间段 + 星期。

---

## 6. 表达

### 6.1 叙述式注入

```
❌ 项目符号：
   - 他叫吕宇轩
   - 他最近很累

✅ 叙述句：
   你记得他叫吕宇轩。前几天他说过最近很累。
```

### 6.2 三档不确定

| confidence | 说法 |
|---|---|
| > 0.9 | 「你叫吕宇轩」 |
| 0.6~0.9 | 「你好像说过你在做量化」 |
| < 0.6 | 「我是不是听你提过」 |

### 6.3 相对时间

```
数据存绝对：2026-10-18
注入用相对：三天前
```

### 6.4 metamemory

```
有 forgotten 的同话题记忆 → 「我好像忘了，你再说一遍」
完全无相关              → 「这事你没跟我说过吧」
```

---

## 7. 安全与权限

### 7.1 敏感内容两档

| 类型 | 处理 |
|---|---|
| 被动听到 | 脱敏，只留影子 |
| **指定记录**（「帮我记一下」） | 完整保存，可归还 |

指定记忆的取回有**三条硬条件**：

```
① 只在私聊（群里问就打岔/「这儿不方便」）
② 必须触发（密码/上次让我记的/那个东西）
③ 触发后给出
```

### 7.2 RBAC

| 能力 | owner | trusted | guest |
|---|---|---|---|
| 注入字数 | 600 | 80 | 0 |
| 写入 | ✅ | ✅ | ❌ |
| 反思 | 深度 | 仅"没人接" | ❌ |
| 改人格 | ✅ | ❌ | ❌ |

**权限跟着人走，不跟着群走。**

### 7.3 第三方信息

```jsonc
{"content": "他在找工作", "via": "third_party", "confidence": 0.7}
```

记到当事人 scope，但置信度低于亲口说的 1.0。

### 7.4 影子

```
内容 → 锁死当事人 scope
影子 → 全局可见「有件事你答应过别人不说」
影响 → 沉淀 self：「别人的事你守得住」
```

---

## 8. 反思（Reflector）

### 信号（纯规则）

| 信号 | 判为 |
|---|---|
| 「不是这个意思」「我没这么说」 | 错 +2 |
| 重复解释同一件事 | 错 +1 |
| 回复骤短（< 上轮 50%） | 错 +1 |
| 追问/展开/接梗 | 对 +1 |

```
错分 ≥ 2 → 反思；对分 ≥ 2 → 强化
```

### 冷处理

```
发现可能错 → 挂起 24h
  再出现 → 确认，写 mistake
  没出现 → 撤案
```

### 错误留档

```jsonc
{"about": "self", "shape": "point", "content": "我以为他讨厌猫，其实只是过敏",
 "strength": {"weight": -0.3}}
```

**负权重 = 羞愧，下次会收着点。**

---

## 9. 媒体与外部源

```jsonc
{
  "about": "world",
  "shape": "point",
  "content": "他给你看过一个讲大肥鱼由来的视频",
  "media": {
    "type": "video",
    "title": "大肥鱼是怎么来的",
    "url": "https://b23.tv/xxxx",
    "summary": "DeepSeek logo 被认成胖鱼，后来全网叫大肥鱼"
  }
}
```

**只存摘要 + 引用，不存内容。**

### 外部源适配器（为未来留口）

```python
class SourceAdapter:
    name: str
    def fetch(ref) -> Evidence
    def summarize(ev) -> str
    def trust() -> float
```

| 来源 | confidence |
|---|---|
| 亲口 | 1.0 |
| 网页正文 | 0.85 |
| 搜索摘要 | 0.7 |
| 视频标题 | 0.6 |
| 自我推测 | 0.5 |

---

## 10. 时间锚点

```
rule + periodic  → 作息「他十二点吃饭」，窗口内 ×1.5
point + annual   → 生日，当天 ×2.0
relation         → 纪念日「认识 100 天」
```

**应验才强化**：她中午问"吃了吗"，你回了 → +0.2。连续三次 → 习惯成立。

节日表硬编码未来 3 年，可配置。

---

## 11. 交互原则

**没有命令，没有删除。**

```
不提供 /memory /forget /dream
全自动；想看问她；想让她忘，用话跟她说
日志只在服务端
```

---

## 12. 成本

| 环节 | 模型调用 |
|---|---|
| 每轮对话 | **0**（检索纯本地） |
| 每晚总结 | 1 |
| 每周整理 | 2（合并 + 复盘） |
| 反思 | 只在出错时 1 次 |

---

## 13. 范围

### v1
```
统一模型 / Source / CAS blob / 四层结构
写入门控 / 检索打分 / 组装 / 表达
衰减淘汰 / 强化 / 反思 / RBAC / 影子 / 时间
```

### v2
```
revert / diff / Distiller / Dream 审批
联想链扩展 / 媒体适配器 / 外部源
```

### 不做
```
命令面 / 手动删除 / 分布式 / DAG 分支 / 模糊化
```

### 随时可加（零 token 代价）
```
GC（无引用 blob 清理）/ 冷压缩（zlib）
```

---

# v3 变更：通用头 + 类型化 payload

**借鉴 PowerContext：加 family，不加字段。**

## 通用头（10 个，锁死）

```jsonc
{
  "id": "n_01",
  "family": "memory",        // memory|example|persona|media|secret|designated
  "revision": 2,
  "state": "active",         // active|forgotten|merged
  "scope": "private",        // private|shared|shadow
  "lineage": {"sources": ["s_01"], "derived_from": []},
  "strength": {"weight":1.2,"confidence":1.0,"arousal":0.6,"valence":0.3,"funny":0.2},
  "time": {"created":"","updated":"","valid_from":"","valid_to":null,"expires":null},
  "said_by": "owner",        // owner|third_party|web|inferred
  "shareable": "private_only"
}
```

## Payload（按 family）

```jsonc
memory:     {text, level, shape, chrono, about, first}
example:    {user, assistant, tags}
persona:    {text}
media:      {type, title, url, summary, shared_by}
secret:     {ref, shadow_text}
designated: {text, trigger, given}
```

## 校验器（每个 family 一个）

```python
MODEL     = require("text","level")
EXAMPLE   = require("user","assistant")
PERSONA   = require("text")
MEDIA     = require("type","title","url")
SECRET    = require("ref","shadow_text")
DESIGNATED= require("text","trigger")
```

## 抽象树

```
impression  印象（他这个人怎么样）  常驻注入
  └ scene   场景（某一次经历）      检索注入
      └ detail 细节（说了什么）      按需下钻
```

## 关系边

```
similar   A ↔ B 相似
causal    A → B 因果
temporal  A ~ B 同期
```

## 检索：激活扩散

```
种子提取 → 激活种子 → 沿边扩散（衰减）→ 按层裁剪 → 取 top-k
```

## 数据表

```sql
blobs(hash, content, at)
ledger(seq, at, op, entity, before_hash, after_hash, reason, prev_hash, self_hash)
nodes(id, family, level, parent, blob, state, scope, strength, time, said_by, shareable)
edges(src, dst, type, weight)
sources(id, umo, at, role, blob, flags)
evidence(node, source)
```

## 代码约束

- 单文件 ≤ 300 行，目标 150
- core 不 import astrbot
- 只有 store 碰 SQL
- 一切写入走 `commit(artifact, op, reason)`
- fail-open：记忆异常不得影响聊天

## 13. 记忆的层级：人格 > 印象 > 记忆 > 事实

注入不是一锅炖，是按重要性排的四层：

| 层级 | 内容 | 归属 | 预算优先级 |
|---|---|---|---|
| 人格 | 她是谁、说话什么调子 | 全局 | 最高，永不砍 |
| 印象 | 对她面前这个人的判断 | 按人（`said_by`） | 高，最多 2 条 |
| 记忆 | 一起经历过的场景 | 按人/会话 | 中，按相关性 |
| 事实 | 名字、地点、时间这些细节 | 按人/会话 | 低，超预算先砍 |

**印象分人**是关键：跟你说话调对你的印象，跟别人说话调对别人的印象。
把某人的性格当成对人的总印象，人味立刻消失。

**印象有轨迹**：每条记忆落库时把自己的 revision 存进 `versions` 表，旧版本不丢。
同一条印象有 ≥2 版时，注入会带一句「（以前觉得…，现在觉得…）」——人对别人的
看法本来就是会变的，说得出这个变化才像人。没变过就不提。

组装按这个顺序排（`recall/assemble.py`），超预算时先砍例子、再砍事实、
再砍细节和场景；人格与印象最后才动。

## 14. 什么时候用记忆

记忆不是每句话都翻。翻一次要花注意力预算，翻错了就是噪声，所以先判断这句话值不值得翻。

### 14.1 读：唤起分档

| 消息 | 处置 | 理由 |
|---|---|---|
| 寒暄（在吗/早/晚安）、问时间、操作类（写代码/查报错） | 不检索，只给常驻层 | 翻出来也是噪声 |
| 明确回忆（还记得/上次/我叫什么）、情绪（累/难过/崩溃） | 放宽检索：k+2、相对阈值 0.3→0.2、预算 ×1.4 | 这类句子答不上就是硬伤 |
| 其余 | 正常证据闸门 | 宁可不给，也不硬凑 |

**常驻层**（人格 + 印象前 2）不受上面影响：它是底色，不是检索结果。

### 14.2 想起：主动浮现

人安静下来会突然想起一件事。`recall/drift.py` 按「越近 × 情绪越强 × 越重要 ×
随机扰动」抽一条，概率随消息长度变化（短句更容易）。影子、秘密、刚讲过的都不浮现。

这不走 query 打分，所以不是检索；它回答的是"她会不会主动提起"。

### 14.3 写：抽取时机与印象修订

- **默认只在夜间批量抽**（23:50），一次把一天的对话抽完，调用次数最少。
- 白天想提前抽也可以，但要同时满足三条：安静够久（`idle_flush_seconds`，默认 0 即关闭）、
  攒够条数（`min_pending`，默认 8）、**这批对话里有值得当场记的事**（计划/日期、
  稳定事实、强情绪）；且每天最多 2 次（`max_flushes_per_day`）。
  纯闲聊攒到晚上一起抽。
- 缓冲落盘（`pending.json`），重启不丢。
- 抽取要 fact / scene / detail / impression 四层，每条带 3~6 个检索用 tags。
- **印象会被改写**：新证据与旧印象重合度 ≥0.85 时只加权重与命中数；
  ≥0.45 时出新 revision（正文换成更准的那句），旧版本留在 blob 与账本里。

### 14.4 没做的

- 不会记错：现在记忆一旦写进去就是"对的"，人会有记岔、会和别人混淆。要做得引入
  置信度与来源冲突检查（ISSUE-0015 的三档不确定是这个方向的第一步）。
- 唤起分档仍是规则；更强的做法是用一条极小的判断模型做意图分类，但这会引入
  额外调用与不确定性，暂时用规则更可控。
- 抽取的成本结构已量过：单次约 600~2700 prompt tokens（其中三到六成命中缓存）
  加 0~300 completion tokens；夜间一次批量是主力，白天即时抽取是补充。

## 15. 开发与分发

WebUI 的 TypeScript 源码保存在 `dashboard/`，发版 CI 构建 `pages/memory/`，
再与必要 Python/SQL 文件组成 Release ZIP。构建产物不进 Git；源码归档用于开发，
安装附件用于部署。后端无需编译或绑定平台环境。
生产页通过 AstrBotPluginPage 桥接器调用经过宿主认证的插件路由；Mock 仅用于开发。
前端划分领域契约、状态/hooks、视图和组件适配层；替换 shadcn 主要调整 `src/ui/`。
后端复用运行中的 DB、Cache、Graph。人工修订在一个事务内校验 revision、写入新版本和账本，
不修改 Source；任务执行器串行处理手动/定时维护，卸载时先取消任务再释放数据库。
生命周期日志保存最近 500 条，1 MiB 轮转并保留一个备份；重启把未结束任务标记为 interrupted。
界面不改变已有 scope 语义：shared/shadow 进入跨会话候选，private 按归属过滤；shadow 正文仍由组装层遮蔽。
详情和限制见 [WebUI 使用说明](webui/README.md)、[管理接口](CONTRACT.md#webui-管理接口)。

## 16. 可选 BM25 字面检索（ISSUE-0024）

默认使用字符 Dice 种子、图激活与本地 BM25 词面信号；`bm25_enabled=false` 时恢复原图检索路径。
字符 bigram 保留词频，不维护人工中文停词表；单字符保留自身 token，纯标点无词项。
正文/标签分别计分，以 `s/(s+8)` 归一化后按 0.75/0.25 融合；配置权重默认 1.0。
词面信号同时用于排序与原证据闸门，不改变可见性、披露和预算规则。

索引从活跃缓存派生，长生命周期 HybridRetriever 按 Cache.version 失效重建；
IDF 与平均长度按本次可见池计算。聊天与只读诊断共用检索器，关闭开关可恢复旧路径。
无需新增模型、运行依赖、网络请求或数据库迁移。完整约定与有限样本效果见
[ISSUE-0024](issues/ISSUE-0024.md)。

零 bigram 重合的语义改写仍不在 BM25 能力内。现有 Retriever 接口保留，
未来语义信号须独立校准，不填入 lexical；后续本地向量的约束记录在 ISSUE-0024，
限定用户预装模型、运行时离线；本次 BM25 可独立运行。
