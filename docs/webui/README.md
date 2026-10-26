# SeekMemory 插件视图

安装 Release 的 `astrbot_plugin_seekmemory.zip`，重载插件，然后从 AstrBot 插件卡片的视图入口打开。
需要支持插件视图和 `astrbot.api.web` 的宿主；已验证 AstrBot 4.28.1 的请求上下文和生命周期 API。
旧入口“插件配置”继续编辑配置；新增“插件视图”用于记忆管理。没有修改 AstrBot 本体导航。
直接打开静态 HTML 或 `pnpm dev:host` 时若没有宿主桥接，会显示连接错误，不会显示示例记忆冒充真实数据。

## 历史私聊初始化

管理员可在“历史初始化”页上传一份 ChatLab v0.0.2 JSON/JSONL 私聊记录，选择 Bot 与目标用户成员，
填写完整 AstrBot 私聊 UMO，再执行预检和明确确认。首版只接受单个 Bot 与单个用户；不接收群聊或批量文件。
页面显示文件元数据、成员消息数、无效行、稳定 Source 数和重复数，不展示对话正文。确认后任务进入现有串行任务执行器，
按 Source 进度展示待提取、已提取和失败数；失败任务可在保留期内重试，管理员也可取消或提前清理。

目前临时上限为 JSON 20 MiB / 10 万条、JSONL 512 MiB / 200 万条，实例暂存空间 1 GiB；
取得代表性 QCE → ChatLab 样本后再校准。所有导入 API 复用 AstrBot 管理员认证，原文件仅存插件私有暂存目录。

## 记忆库

- 六种家族：memory（事实、场景、细节、印象）、persona、example、media、secret、designated。
- 支持关键词、类型、状态、scope、精确来源会话筛选；分页、版本对比、关联跳转、手机抽屉与深浅主题。
- 详情的“编辑与审计”提供原始 JSON、当前 header/lineage、历史 blob、原始来源证据和实际账本。
  来源或账本缺失时显示空集合，不补造历史。
- “主体与时间”区分记忆主体 ID、说话人标记和主体类型，并显示事件/创建时间与有效期。
  新版抽取优先采用事件时间；旧记录缺失时显示“未记录”，不会从说话人或更新日期推算。

| scope | 当前召回规则 |
|---|---|
| private | 仅归属会话；缺少归属时回退配置的 owner_umo，仍无归属则不进入候选 |
| shared | 跨会话进入候选，仍受召回相关性、交付与预算等规则影响 |
| shadow | 跨会话进入候选，组装时遮蔽正文，只输出影子句 |

管理员可以检查全部数据。“来源会话”是溯源和筛选维度，不代表 shared 被限制在来源群。
召回沿用上游 v0.3.0 的披露判定：检索选中的记忆还会根据主体和场景决定全文、改述、提示或静默。
scope 候选可见不等于一定注入全文；诊断页的“逐条披露结果”显示 ID 与全文、改述、提示或静默结果。
该列表仅覆盖后端返回的检索选中项，不包含所有常驻或指定交付记录；最终注入还受预算限制。
本次没有另行修改群聊识别或跨群共享政策；可用召回诊断核对具体 UMO 和说话人。

## 修订、遗忘与恢复

在编辑页修改 JSON、scope 或状态，填写原因并勾选确认后保存。
服务端使用既有 family 校验器检查内容，保留 ID/family/来源/其他头字段，产生 revision + 1。
旧版本、blob 和 Source 不被覆盖；人工修订通过上游 Artifact 内核提交，保留 subject_id 和版本级来源证据。
账本记录修改原因和前后修订号，内容哈希见版本的 blob 字段；旧账本条目按原始记录展示。
同内容但仅状态变化时，前后 blob 可以相同，头部快照仍记录新版本。

保存携带读取时的 revision。其他写入已改变该记录时返回冲突并保留草稿；重新加载后再核对保存。
遗忘可恢复为 active；merged 不能独立恢复，也不能用状态编辑伪造合并，避免破坏派生关系。
“载入该版本内容到修订草稿”只加载 payload，需返回修订页检查当前 scope/状态并显式保存为新版本。
人工编辑不自动重算头部主体 ID、时间或既有 similar/temporal 图边；需要结合关联与诊断检查，后续整理沿用原有维护行为。

## 运行与任务

运行页显示引擎、账本哈希链、日志持久化、模型配置、定时任务数量和各会话待抽取消息。
模型检测只检查当前 provider 配置，不发送模型请求，也不保证网络/配额可用。
配置仍在 AstrBot 插件配置页修改；此处仅展示白名单配置字段。

- **立即抽取**：按会话选择模型、按话题分批，复用去重和写入流程。无待处理消息时直接完成。
- **每周整理**：执行既有衰减、相似合并和人格提炼；不额外调用模型。
- **取消**：请求取消当前任务。已完成的写入不会撤销；同步整理可能在取消请求处理前已经完成。

维护任务共用单任务执行器，运行期间人工编辑被拒绝。模型调用异常/取消时，未成功完成的会话
仍保留在 pending.json；超过批次话题上限的消息和调用期间新到的消息不会被清空。
未配置模型的会话保留消息；没有可用模型时不占用当日抽取次数。单个会话失败不会阻止同批其他可用会话处理，
批次结束后仍标记失败以便排查。积压触发沿用上游 backlog_flush_at 和安静窗口规则，运行页显示对应配置。
抽取中已有的逐条容错仍保留：任务完成不保证每条模型输出都写入，需同时查看 warning、written 和 skipped 计数。
v0.3.1 沿用上游话题分段与 TTL；`max_sessions_per_flush` 保留原配置名，当前按话题限制批次数量。
运行页展示每个待抽取话题的会话、消息数和最早消息时间，并保留会话汇总。
“抽取策略”显示实际积压阈值、话题 TTL 和每批话题上限；TTL 是抽取触发条件，不是自动删除期限。
“待提交强化记忆”是 checkpoint 尚未持久化的记忆数量，与待抽取消息分开计数。
抽取阶段日志含 session/topic，记忆主体与事件时间采用上游解析规则。
定时任务包含夜间抽取、每周整理、空闲抽取和 checkpoint 四个循环。
插件卸载/热重载会取消并等待任务、清理本实例路由、保存缓冲，提交待处理的召回强化 checkpoint 后关闭数据库。

## 召回诊断与日志

诊断输入查询消息、完整会话 UMO 和实际说话人 ID，复用真实 scope/召回/组装逻辑，显示预计注入文本、
决策计数及 scope 候选/排除 ID。不会调用模型，不改数据库，不消耗 designated 的一次性交付状态。
它只预演记忆模块，不模拟完整聊天链路；探索采样可能导致多次结果不同。

生命周期日志记录启动、停止、召回摘要、人工编辑、诊断及任务的 queued/running/succeeded/failed/
cancelled/interrupted 状态，可按类型、状态、级别、模块、任务 ID 和文本组合筛选。
新日志显示模块、相对文件、函数与行号，展开可看显式业务字段和异常调用位置。
抽取细分模型调用、解析、去重、校验、写入、印象修订；每周整理细分衰减、合并、人格提炼，
各阶段记录耗时并自动关联任务。旧日志没有源码位置时会明确标注，不伪造历史。
异常仅记录类型与调用位置，不采集局部变量、源码正文或异常消息。
内存/API 最多 500 条，`lifecycle.jsonl` 超过 1 MiB 轮转，保留一个备份；重启恢复范围限于保留的日志。
只记录计数、操作 ID 和错误类型，不记录对话/模型正文。来源证据在管理员详情页单独显示。
任务运行时每 2 秒刷新；空闲时手动刷新。这不是全量 AstrBot 控制台日志，也不是永久审计存档。

## 开发与截图

`cd dashboard && pnpm dev` 可独立运行全部页面，Mock 编辑只存在内存，任务不会调用模型。
Mock 诊断仅演示文本匹配和不同披露级别，不能用于验证真实召回规则。源码、Mock、测试和截图不进入安装包。
完整工程说明见 [dashboard/README](../../dashboard/README.md)。

当前主题使用冷蓝主色、浅蓝辅助色和少量淡粉装饰；实色导航、统计卡和浅蓝标题区形成层次。
成功、警告、错误分别使用绿色、琥珀色和红色，并保留文字说明；深色模式使用深海军蓝底色。

下图均为虚构 Mock 数据，布局与生产页共用组件。
截图独立存放在 [webui-previews 资源分支](https://github.com/SXP-Simon/SeekMemory/tree/webui-previews)，代码 PR 与安装包不包含 PNG。
[主题与功能预览索引](https://github.com/SXP-Simon/SeekMemory/tree/webui-previews#readme) 覆盖九种类型、版本关联、来源账本、任务确认、诊断和日志筛选。
九种类型为四个 memory level 加五个独立 family，均复用统一列表和详情，不是九套专用编辑器。

![记忆库](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/cbb1d2597e237da49560f28694df8affb77c588c/images/theme-memory-light.png)
![手动修订](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/95812b0d36ebb76e859ebd2c4033fe784f87b923/images/memory-attribution.png)
![运行检测和任务](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/95812b0d36ebb76e859ebd2c4033fe784f87b923/images/topic-runtime.png)
![生命周期日志](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/cbb1d2597e237da49560f28694df8affb77c588c/images/theme-logs-light.png)
![手机深色布局](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/cbb1d2597e237da49560f28694df8affb77c588c/images/theme-mobile-dark.png)

![召回诊断命中与 scope](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/95812b0d36ebb76e859ebd2c4033fe784f87b923/images/recall-disclosure.png)
旧主题功能参考（当前配色见上图）：

![无命中诊断](https://raw.githubusercontent.com/SXP-Simon/SeekMemory/3152766d0c6cd70a84ca5b1485d0983ded97c5e2/images/diagnostics-empty.png)

## Run Trace（运行轨迹）

管理页的“运行轨迹”展示一次 Agent 的模型请求、工具步骤和发送事件。选择筛选条件后，
点击运行查看时间轴；“筛选与披露详情”显示 gate 和披露等级，点击记忆 ID 打开已有审计抽屉。
“记忆已注入”不代表模型在回答中引用；“回复已发送”单独显示。筛选可以重叠。

默认保留 7 天、最多 5000 个事件，支持 `trace_retention_days` / `trace_max_rows` 配置。
用“刷新轨迹”手动更新；截断或保存失败会显示提示。Mock 预览使用虚构轨迹，不连接机器人。
