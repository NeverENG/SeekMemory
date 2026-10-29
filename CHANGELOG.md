# 变更记录

## 0.5.1 — 2026-10-28

### 中文

- 内部卫生：增加 services 的 domain/ports 明确入口及实际依赖类型；分开管理查询与修改，抽出纯人格证据和版本规则，保留原导入及返回值，同步双语职责说明。

- 修复开口策略在 `wake_prefix` 为空时把每条群消息误判为「被 @」：映射层改为只认消息组件里指向 `self_id` 的 At，不再使用 `is_at_or_wake_command`。此前陌生人闲聊都会触发回复。
- 策略参数化：新增 `attention_policy_enabled`（总开关）、`attention_followup_rounds`（点名后陪聊轮数，默认 3）、`attention_owner_always_reply`（主人是否每条都回，默认开）；组合层从配置读取并传给 `DefaultAttentionPolicy`。
- 回归测试覆盖：At 组件识别、wake-all 不再算点名、主人开关、陪聊轮数。

### English

- Internal hygiene: add explicit services domain/ports entries and actual dependency types; separate management reads from commands and extract pure persona evidence/revision rules, retaining imports and return shapes with mirrored responsibility documentation.

- Fix the attention policy treating every group message as an @-mention when `wake_prefix` is empty: the host mapping now only accepts a real `At` component targeting `self_id` instead of `is_at_or_wake_command`. Previously ambient stranger chatter triggered replies.
- Make the policy configurable: `attention_policy_enabled` (master switch), `attention_followup_rounds` (follow-up rounds after being called, default 3) and `attention_owner_always_reply` (reply to every owner message, default on); composition reads them into `DefaultAttentionPolicy`.
- Regression tests: real At detection, wake-all is not a mention, owner switch, follow-up rounds.

## 0.5.2 — 2026-10-28

### 中文

- 修复宿主钩子被同名闭包互相覆盖的问题：`_register` 生成的包装函数原来全部叫 `handler`，而 AstrBot 用 `module + __name__` 生成 handler 唯一名，导致只有第一个 hook（`inject_memory`）注册成功，`attention_gate` 等全部丢失——开口策略因此从未真正执行。现在每个 hook 显式设置 `__name__`，并加源码级回归断言。
- 现象对照：升级到 0.5.x 后线上 30 分钟 172 条入站 / 94 条回复 / 0 条策略决策；修复后 `attention_gate` 正常拦截陌生人闲聊。

### English

- Fix host hooks overwriting each other because every wrapper closure was named `handler`: AstrBot derives the unique handler name from `module + __name__`, so only the first hook (`inject_memory`) registered and `attention_gate` was lost, meaning the attention policy never ran. Each wrapper now sets `__name__` explicitly, with a source-level regression assertion.
- Symptom: after upgrading to 0.5.x the live instance produced 172 inbound events / 94 replies / 0 attention decisions in 30 minutes; after the fix `attention_gate` intercepts ambient group chats again.

## 0.5.3 — 2026-10-28

### 中文

- 修复 `AttentionHooks` 访问 `_may_observe` 抛 `'Main' object has no attribute '_may_observe'`：该 helper 在 `host.hooks` 上，不在宿主本身；现在显式委托 `host` 或 `host.hooks`，并加回归测试。

### English

- Fix `AttentionHooks` raising `'Main' object has no attribute '_may_observe'`: the helper lives on `host.hooks`, not the host object; it now delegates explicitly and has a regression test.

## Unreleased

### 中文

- app 卫生：保留兼容入口，内部区分纯规则、状态变化、执行和补写；全量规范中英双语源码说明，同步双语文件职责、接口及验证入口。存储和宿主转接暂留原处，供后续跨模块整理。

- 运行时：确认发送后保留进程内凭据，写回失败仅补状态、原始消息/队列及审计；关闭后台发言及停止时仍补写。保存失败可被编排识别，文件失败不覆盖旧状态，新增审计使用稳定运行编号。不改数据库结构或旧记录，不保证断电后绝对不重发。

- 夜间整理：分离纯时间/预算规则；台账结束失败如实返回失败及已完成数量，错误不再保存异常正文，诊断失败不影响整理结果。

- 修复强化提交成功但缓存失败后的重复提交；缓存补偿读取最新版本，未提交命中和缓存补偿分别保留。

- 内部接口：增加 `app.domain`，并在 `app.ports` 集中列出应用层提供的能力与外部依赖；补齐中英接口清单、逻辑复杂度及职责缺口。保留原导入路径和实现位置，未改变业务规则、持久化格式或公开配置。

- 文档：补齐 core 能力与现有测试的对应入口、定向验证命令及证据范围；澄清测试分层混用、旧跑分的样本权重与字数指标，以及报告生成不等于质量验收。测试、跑分和运行代码保持不变。

- 内部卫生：算法阈值与系数在所属 core 文件内具名维护；关系校验和追踪复用领域词表，互动规则复用已有默认概率。保持策略数值、边界判断、配置及持久化约定不变。

- 内部接口：将 `core.interfaces` 拆为对外能力入口 `core.domain` 和外部依赖声明 `core.ports`，移除图的延迟导入绑定。内部调用需更新导入路径；现有领域实现入口、策略数值和外层契约保持兼容。

- 内部架构：树读写集中迁入 `services.TreeService`，所需存储和缓存接口迁至 `app/ports.py`；内部 Python 调用需替换原 `core.tree.Tree` 入口。保持宿主、管理接口、配置、持久化格式及原有读写行为兼容。

- 人格小铺支持兼容旧 JSON 的完整包导入/导出、PNG 封面及许可证预览；封面经管理员鉴权读取，图片校验与打包覆盖大小、尺寸、损坏及路径边界。更新保留旧包备份，不改变 Persona/Source 数据结构；旧代码回退前需导出纯设定 JSON。替换或取消导入会丢弃迟到的封面读取结果。角色内容与正式插画留待后续。

- 星图每次加载最多读取 120 条记忆和 240 条关联，默认显示 80 条，40/80/120 切换不再请求；移除千节点选项与后台布局，避免预读过多记忆。

- 将星图读取改为数据库限量快照与批量关联查询；补齐抽屉中的键盘列表、聚焦和关联视图，修复普通 HTTP 页面保存人格包的随机 ID 兼容性。保持数据库格式与公开配置不变。

- 兼容 v0.5.0 的 AstrBot 包结构，修正内置人格包路径，保留上游动作审计及自动测试发现机制；验证人格包、Dream 历史及重启恢复。无额外数据库或配置变更。

- 同步 v0.4.3 后的宿主运行时，保留人格包与 Dream 控制台接线；补齐重载及启动失败重试验证，将控制台文档迁入中英双语目录，日志增加“允许回复／本轮不回复”状态筛选。无新增数据库或配置变更。

- 按界面反馈移除星图数量提示、关联筛选入口、底部键盘列表及重复详情按钮；浮动卡片的详情按钮跟随记忆点配色，明黄、淡绿使用深色文字。

- 修复星图入场计时停止后亮面残留：高亮在入场结束前淡出，常态只随波纹短暂亮起；将土黄、橄榄黄绿调整为明黄、淡绿，并统一明暗主题。

- 收紧星图节点光晕，改用单路接力的淡色连线脉冲，无亮头或拖尾；入场沿球面由左向右分支扩散，镜头稍滞后于前沿，在 6.6 秒内逆时针环绕一整圈，同步拉远并居中，避免末尾额外平移，支持中途接管视角与减少动态效果。

- 星图改用高对比发光节点，面片只随波纹或入场短暂亮起；默认显示最近更新 80 条（可选 40/80/120），随数量放大默认半径，进入/刷新时播放点→线→面→体动画。点击横幅展开既有详情接口返回的正文与元信息，保留受保护内容遮蔽并丢弃过期请求。

- 记忆星图改为可旋转的立体记忆球，支持同类分组、分类配色、呼吸/波纹/流光、悬停凸起及信息框、点击固定与缩放；球面网格与真实关联区分呈现，修复交互时重建画布造成的闪动，筛选收进抽屉；生命周期日志改为只读控制台，支持定时刷新、暂停更新、自动跟随及展开详情，保留既有筛选与脱敏接口。

- 根据 DeepSeek 首页与 Harness 实际页面调整明暗主题：浅蓝白底与淡网格、石墨黑底与柔和蓝光；侧栏、面板和抽屉加入适量磨砂玻璃层次，补齐页面进入、侧栏折叠与悬停动效，并适配减少动态效果偏好。

- 记忆筛选收拢为单一入口，提供带解释的类型/范围选项、明确的记忆条数和可逐个取消的条件标签；修复侧栏收起后文字溢出及预览页底部按钮超出视口。

- 记忆库改为单栏列表：统计收拢为摘要，集中类型/状态/范围/会话筛选并支持统一重置，详情改为点击后打开抽屉。

- 记忆库移除重复的独立侧栏，将类型及数量合并至列表筛选，统一桌面与窄屏入口。

- 首页采用居中人格展示与下方运行/成长分栏，调整标题、胶囊按钮与留白；按用户提供的画风和人设参考生成透明 Q 版头像，替换首页与小铺的鱼插画。

- 管理面板统一蓝白黑配色，图表与深色模式共用主题；移除装饰英文、重复说明与页脚标语，以留白和标题层级组织内容。

- 控制台改用分组式左侧导航，支持桌面折叠和窄屏图标栏，连接状态与刷新移至侧栏底部。

- 人格控制台接入历史版本回滚、差异比较与变化原因；安装时校验预览内容，按版本显示已安装状态；Dream 日志区分预算停止与完成，并显示调度开关。新增控制台接口需与 dashboard 同步更新，不涉及数据库迁移或配置变化（#82 / #83）。

### English

- Clarify app pure rules, transitions, dispatch and write-back behind compatible entries; standardize bilingual source documentation and update mirrored responsibility/interface/verification maps. Storage and host adapters remain in place pending cross-module inventory.

- Retain process-local receipts after confirmed sending and retry only state, Source/projection and audit writes, including with speaking disabled and at shutdown. Surface storage failures, preserve old file state and derive stable IDs for new audit rows. No schema or historical-row changes; crashes may still lead to resend.

- Separate daily time/budget rules; report journal finish failure with completed counts, omit exception bodies, and isolate diagnostic failures.

- Prevent duplicate reinforcement after a successful commit followed by cache failure; repair from the latest head and retain uncommitted hits separately.

- Internal interfaces: add `app.domain` and centralize required capabilities in `app.ports`; document the provided/required interface inventory, logical complexity, and responsibility gaps in both languages. Existing import paths and implementation locations remain available; business rules, persisted formats, and public configuration are unchanged.

- Documentation: map core capabilities to existing tests, focused commands and evidence limits; clarify mixed test layers, fixture-weight/character-count metrics in the legacy benchmark, and report generation versus quality acceptance. Test, benchmark and runtime code remain unchanged.

- Internal hygiene: name algorithm thresholds/factors within their owning core files; relationship validation and trace reuse domain vocabularies, and interaction rules reuse existing default probabilities. Policy values, boundary comparisons, configuration and persisted contracts remain unchanged.

- Internal interfaces: split `core.interfaces` into the provided `core.domain` entry and required declarations in `core.ports`, removing lazy graph binding. Internal callers must update imports; existing domain implementation entries, policy values and outer contracts remain compatible.

- Internal architecture: move tree orchestration to `services.TreeService` and its storage/cache ports to `app/ports.py`; internal Python callers must replace `core.tree.Tree`. Host/management contracts, configuration, persisted formats, and existing read/write behavior remain compatible.

- Add complete persona-pack import/export compatible with legacy JSON, PNG artwork and license previews. Serve artwork through administrator authentication and validate packaging, size, dimensions, corruption and path boundaries. Preserve backups on update without changing Persona/Source schemas; export seed-only JSON before reverting to older code. Discard late cover reads after an import is replaced or cancelled. Character content and final artwork remain deferred.

- Read at most 120 graph nodes and 240 associations on load, display 80 nodes by default, and switch between 40/80/120 locally. Remove the 1,000-node option and background layout to avoid excessive prefetching.

- Bound graph reads in SQL and batch association queries; add a drawer-based keyboard list, focus and neighborhood actions, HTTP-compatible random persona-pack IDs. Database formats and public configuration are unchanged.

- Integrate the v0.5.0 AstrBot package layout, correct the built-in persona-pack path, and retain upstream action auditing and automatic test discovery. Verify persona packs, Dream history and restart recovery without additional database or configuration changes.

- Integrate the post-v0.4.3 host runtime while retaining persona-pack and Dream console wiring. Verify reload and failed-start retry, move console documentation into the bilingual tree, and expose allow-reply/skip-reply log filters. No additional database or configuration changes.

- Remove the graph count, relation filter, bottom keyboard list and duplicate detail action. Match floating-card detail buttons to their memory node colors with dark text on bright yellow and light green.

- Fade memory-sphere assembly highlights before the entrance clock stops, preventing permanently lit facets while retaining transient ripple illumination. Replace ochre and olive tones with clear yellow and light green in both themes.

- Tighten node halos and replace travelling heads/tails with one muted, continuous edge-pulse relay. Sweep the entrance left to right along branching mesh paths while the camera trails the frontier through exactly one counterclockwise turn in 6.6 seconds, pulling back and centering continuously without a separate final translation; support interaction takeover and reduced motion.

- Use higher-contrast luminous nodes and transient ripple/assembly facets. Show the 80 most recently updated memories by default (40/80/120 choices), scale the default radius with density, and assemble points → lines → faces → volume on entry/refresh. Expand annotations on selection using the existing detail API, retaining protected-content masking and discarding stale replies.

- Rework the memory map into a rotatable 3D memory sphere with category patches, muted colors, breathing/ripple/flow motion, raised hover nodes, annotations, pinned selection and zoom. Distinguish surface geometry from real relationships and avoid canvas recreation during interaction; move filters into a drawer. Present lifecycle logs as a read-only console with polling, pause, follow-latest and expandable details, retaining existing filters and sanitized APIs.

- Adapt light/dark themes from the live DeepSeek and Harness pages: icy-blue backgrounds and a faint grid, graphite surfaces and soft blue light. Add restrained frosted navigation, panels and drawers, plus page-entry, sidebar and hover motion with reduced-motion support.

- Consolidate memory filters into one entry with explained type/scope choices, explicit record counts and removable filter chips; fix collapsed sidebar text overflow and off-screen preview footer controls.

- Simplify the memory library to a single list with inline statistics, unified category/state/scope/session filters and reset, and on-demand detail drawers.

- Remove the duplicate memory-library sidebar and move category counts into the list filter, shared across desktop and narrow layouts.

- Recompose the home page around a centered persona and separate activity/history columns, with lighter headings, pill buttons and more whitespace; replace the home/store fish with a transparent chibi head generated from user-supplied style and character references.

- Unify the dashboard around blue, white and neutral black, including charts and dark mode; remove decorative labels, repeated introductions and footer slogans in favor of spacing and clear headings.

- Replace console top navigation with a grouped left sidebar, desktop collapse and a compact icon rail on narrow screens; move connection status and refresh to its footer.

- Connect persona rollback with version diffs and change reasons; validate previewed pack content before installation and show installed versions accurately. Dream distinguishes budget stops from completion and reports scheduling state. Ship the new console API and dashboard together; no database migration or configuration change (#82 / #83).

## 0.5.0 — 2026-10-28

### 中文

- 修复 Source 回查的新鲜度排序：带时区时间戳与本地时间混用时，按实际经过时间计分，避免近期消息被当成旧消息；无时区时间按本地时间解释，不修改历史数据或配置。
- 修复印象合并的部分提交和成功误报：强化或改写旧印象与退役新印象通过同一事务提交，成功后再更新缓存；写入失败和版本冲突由服务层记录。两条变更统一按 merge 审计，沿用现有数据库格式（#138）。
- 新增默认关闭的主动决策纯策略，显式处理到期时间、安静窗口、冷却、重试、忽略连击退避和最大尝试次数；有界选择器优先派发最早到期会话，其余保持待处理。
- 扩展 `runtime_episodes` 保存无正文的动作尝试与终态；重复回调幂等，每个 action 最多保留一个终态，并沿用现有保留清理。
- 新增 `AgentRuntime.schedule_proactive()` 和 AstrBot `proactive_idle_seconds` 排期入口；主动策略从纯策略接到真实 worker。宿主发送动作也进入 action ledger，成功/失败均形成无正文终态。
- 将 AgentRuntime 默认注意力收敛为单一 `DefaultAttentionPolicy`：主人/私聊/直接提及回复，非主人直接提及后按说话人保留 3 轮后续回复；移除默认路径中的额度、preset、阈值、关系/热度信号和场景提示，策略结果只通过 `AttentionDecision` 向 Runtime 返回通用状态补丁。
- 收口 Runtime action 链路：新增 `ActionExecutor` 统一 attempt/terminal 与 `ActionPort` 执行，`ActionMessageSender` 仅作为 `SEND_TEXT` 兼容适配器；AstrBot 发送/工具审计统一走 ActionExecutor，不再直接操作 ledger。

### English

- Fix Source recall recency ranking when offset-aware timestamps are mixed with local time: score actual elapsed time instead of treating recent messages as old. Naive timestamps use local time; stored data and configuration are unchanged.
- Fix partial commits and false success in impression consolidation: updating the existing impression and retiring the incoming one share a transaction, with cache updates after commit. Write failures and revision conflicts reach service-layer error handling. Both changes are audited as merge operations using the existing database format (#138).
- Add a default-closed pure proactive policy for due times, quiet windows, cooldown, retry, ignored-streak backoff and maximum attempts. Its bounded selector dispatches the oldest eligible sessions first and leaves the rest pending.
- Extend `runtime_episodes` with content-free action attempts and terminal outcomes. Duplicate callbacks are idempotent, each action keeps at most one terminal outcome, and existing retention cleanup applies.
- Add `AgentRuntime.schedule_proactive()` and the AstrBot `proactive_idle_seconds` scheduling entry so the pure proactive policy reaches the real worker. Host send actions now enter the action ledger with content-free success/failure terminals.
- Collapse the default AgentRuntime attention path to one `DefaultAttentionPolicy`: owner, private, and direct attention reply; a non-owner direct interaction retains a per-speaker three-round follow-up window; quota, presets, thresholds, relationship/heat signals, and scene hints are removed from the default path. Policy results return a generic state patch through `AttentionDecision`.

- Collapse the runtime action path: `ActionExecutor` now owns attempt/terminal coordination around `ActionPort`, while `ActionMessageSender` is only a `SEND_TEXT` compatibility adapter. AstrBot send/tool audit now goes through ActionExecutor instead of touching the ledger directly.

## 0.4.3 — 2026-10-27

### 中文

- 开口策略改为「主人必回、陌生人只在被 @ 或叫名字时回，且点名后陪聊 3 轮」：新增 `quota_gate` 纯函数（私聊/主人恒放行、点名刷新额度、普通消息消耗额度），修复 `stranger_quota_mode=off` 时连 @ 也被拦、以及 WAIT 决策不消耗额度的问题；新增 `attention_address_names`（默认「大肥鱼,肥鱼」），叫名字等同被点名。配置：`stranger_quota_mode=fixed:3`、`attention_thresholds={"owner_cooldown_seconds": 0}`。

### English

- Attention now means: the owner always gets a reply; strangers only when @-mentioned or called by name, then three follow-up rounds. Add the pure `quota_gate` (private/owner always allowed, mention refreshes quota, ambient messages consume it) and fix two bugs: `stranger_quota_mode=off` blocked even @-mentions, and WAIT decisions never consumed quota. Add `attention_address_names` (default `大肥鱼,肥鱼`). Deployed config: `stranger_quota_mode=fixed:3`, `attention_thresholds={"owner_cooldown_seconds": 0}`.

## 0.4.2 — 2026-10-27

### 中文

- 修复运行时交付与恢复：冷却从实际发送完成计时，失败从实际失败时刻退避；普通和延迟回复仅确认本轮覆盖的消息。延迟任务取消或重启后仍可有限重试，轮询与直接调用共用并发上限。复用现有会话状态字段，无数据库迁移或新增配置；宿主不再用待抽取队列长度推算未读数。AstrBot 通过同一适配层时间钩子统一为 UTC+8，新时间带 +08:00 标记，内核读取格式和历史 Source 保持不变；没有时区的旧值保留原样。
- 记忆感知的开口策略默认开启：AstrBot 事件经 `adapters/astrbot_event.py` 映射为 `RuntimeInput`，`adapters/astrbot_attention.py` 调策略后放行/`stop_event`；预设 quiet/balanced/chatty/intimate，陌生人额度按关系与配置，场景提示注入系统提示。group_guard 与 persona_gate 因此停用，由 SeekMemory 接管；连发合并与主动私聊仍由 message_merger / ping 插件负责（等 #116/#117）。基础件：`RuntimeInput` 向后兼容扩展多平台字段（scene/conversation_id/thread_id/role/addressed/reply_to_me 等，scene 预留 comment 评论区）；新增 `adapters/astrbot_event.py`（宿主事件→RuntimeInput 纯映射）与端到端策略测试；新增 `app/runtime/signals.py`（关系/相关度/热度/时间窗信号）、`attention.py`（纯函数策略，硬条件优先、主人冷却、陌生人关系额度）、`scene_hints.py`（时间/身份/亲疏提示）、`topics.py`（主动话题候选与冷却过滤）。只新增契约与纯函数，不改变线上行为（#123）。
- 事件分层决策：暂不引入 HostEvent/ContentPart/EventCodec，宿主适配层直接产出扩展后的 `RuntimeInput`；演进触发条件见 `docs/zh/architecture/event-contract.md`。

### English

- Memory-aware attention is on by default: AstrBot events map to `RuntimeInput` via `adapters/astrbot_event.py`, `adapters/astrbot_attention.py` runs the policy and allows/`stop_event`s; presets quiet/balanced/chatty/intimate, stranger quota by relationship and config, scene hints injected into the system prompt. group_guard and persona_gate are retired in favour of SeekMemory; message merging and proactive DMs stay in the message_merger / ping plugins until #116/#117. Groundwork: backward-compatible multi-platform fields on `RuntimeInput` (scene/conversation_id/thread_id/role/addressed/reply_to_me, with `comment` reserved for comment sections); add a pure host-event mapper (`adapters/astrbot_event.py`) and end-to-end policy tests; new pure modules `signals.py` (relationship/relevance/heat/window), `attention.py` (hard conditions first, owner cooldown, stranger quota by relationship), `scene_hints.py` (time/role/closeness hints) and `topics.py` (proactive topic candidates with cooldown filtering). Contracts and pure functions only; no live behavior change (#123).
- Event layering decision: no HostEvent/ContentPart/EventCodec yet; host adapters emit the extended `RuntimeInput` directly. Evolution triggers are recorded in `docs/zh/architecture/event-contract.md`.

- 修复 seed 人格注入被 180 字上限截断：`_persona_sentence()` 不再复用单条记忆的清洗函数，人格整段进入常驻层，长度只由注入预算约束；新增 `scripts/bootstrap_persona.py`（含 `--dry-run`）与回归测试 `tests/test_persona_injection.py`（ISSUE-0034 / PR-0034）。

- 新增 Dream 分诊 tradeoff 评估：冻结 40 个合成主题，跑生产 `DreamCycle -> IngestService.flush` 路径，用确定性 fake provider 记录调用、token、分诊选择、抽取量、重要事实召回、错误记忆/重复率、bot 行为/自我印象覆盖和 pending 数量/年龄，并对比 `cc814ce` 与 `d9fc248`。当前按预注册阈值判为 `NOT_ACCEPTED`：调用 -80.0%、token -72.8%，但重要事实召回 65.2%、自我印象覆盖 0/1，pending 每晚线性增长 8 个主题。不修改分诊算法，不新增服务/表/写入路径。

- 修复 Windows 补充验证发现的问题：状态接口定义补齐已有的原文辅助检索预算字段，90 天模拟重启后正确关闭数据库连接，宿主测试按初始化权限和当前运行入口验证消息捕获及记忆注入。记忆注入异常日志仅记录异常类型，避免泄露原文或路径。实际接口响应、数据库格式和配置保持不变。

- 将仓库约定拆分为 repo skill 与四份主题 reference，通过 Codex/Claude Code symlink 共用；简化 PR 模板以收集范围、验证和兼容性证据。扫描器待 UI 规则明确后再加入。PR CI 继续全量检查，本地验证按风险选择。

### English

- Fix runtime delivery and recovery: cooldown starts at confirmed send completion, backoff starts at failure, and normal/deferred replies acknowledge only input covered by that run. Deferred work remains recoverable with bounded retries after cancellation or restart, and scans/direct calls share a concurrency limit. Existing session fields are reused without database migration or new configuration. The host no longer infers unread counts from the extraction queue. AstrBot uses one adapter time hook for UTC+8 with an explicit +08:00 offset on new timestamps, preserving kernel read formats, historical Sources, and legacy values without timezone information.

- Fix seed persona injection being truncated at 180 characters: `_persona_sentence()` no longer reuses the per-memory cleaner, so the whole persona reaches the pinned layer and only the injection budget bounds it; add `scripts/bootstrap_persona.py` (with `--dry-run`) and the `tests/test_persona_injection.py` regression suite (ISSUE-0034 / PR-0034).

- Add a Dream triage tradeoff evaluation: a frozen 40-topic synthetic corpus runs the production `DreamCycle -> IngestService.flush` path with a deterministic fake provider and records calls, tokens, triage selection, extraction yield, important-fact recall, modeled false-memory/duplicate rates, bot-behavior/self-impression coverage and pending count/age, comparing `cc814ce` with `d9fc248`. The pre-registered thresholds currently return `NOT_ACCEPTED`: calls -80.0% and tokens -72.8%, but important-fact recall 65.2%, self-impression coverage 0/1 and pending growth of 8 topics per night. No triage algorithm change, new service/table or write path.

- Fix findings from supplemental Windows validation: declare the existing Source recall budget fields in the status contract, close reopened database connections in the 90-day simulation, and exercise message capture and memory injection through initialized access policies and current runtime boundaries in host tests. Memory injection error logs now record only the exception type to avoid exposing message text or paths. Actual API responses, database format and configuration remain unchanged.

- Split repository guidance into a repo skill and four focused references, shared through Codex and Claude Code symlinks; simplify the PR template to collect scope, verification and compatibility evidence. The UI scanner is deferred until its rules are settled. PR CI remains comprehensive; local checks are selected by risk.

## 0.4.1 — 2026-10-25

Persona foundation：seed 人格初始化、Dream 人格增量合成、同一 lineage 回滚和 90 天生命周期回归。

- **Persona file bootstrap**：新增 persona 文件 schema、corpus 质量门、seed provenance 和单一直系人格链；
  seed 只初始化一次，不伪造 Source，不复制完整 corpus 到后续 revision。
- **Dream persona synthesis**：Dream 基于 active persona、self-impression 和 shared memory 摘要做增量人格 revision；
  每周期最多一次模型调用，失败保留旧人格，默认 7 天间隔。
- **Rollback API**：`POST manage/rollbackPersona` 从历史 revision 创建新的 active revision，不删除历史。
- **测试**：新增 90 天 fake-clock 生命周期、配置/时间边界、失败原子性、Provider 响应兼容和 90 天安全测试骨架。
- 新增 `persona_synthesis_enabled` / `persona_synthesis_interval_days` 等配置；无数据库 schema 迁移。

- Added memory-first Source evidence recall: when Artifact selection is weak, one bounded recent
  Source query can discover derived Artifacts through the existing disclosure path. Source text is
  internal evidence only and never enters the prompt; `source_recall_enabled=false` restores the
  old path.
- Added exact extraction `WriteOutcome`/`usage_snapshot()` accounting and `dream_max_calls` as the
  primary Dream call budget. `dream_token_budget` remains an optional secondary guard; turn-only
  extraction chunking and committed-work maintenance are preserved.
- Added deterministic Dream-only importance triage before provider resolution. High-value topics
  are selected locally; low-value topics remain pending and unmarked. Normal nightly/idle FIFO
  selection is unchanged. The known tradeoff is narrower self-impression coverage.
- Dream triage now packs same-session prepared topic chunks into one extraction call within
  `dream_batch_tokens` (default 6000); cross-session batching remains out of scope.
- Multi-topic Dream batches now require evidence IDs from one topic on every extracted
  item so lineage stays scoped to cited Sources; single-topic legacy fallback is unchanged.
- Dream triage now scores user corrections and behavior-relevant paired assistant replies,
  allowing bot behavior scenes to feed the existing self-impression path without converting
  generic or assistant-only messages.

- Invariant hardening: scoped identity dedupe, source identity, failure recovery, oversized topics,
  privacy output, reinforcement truth, lineage/cache consistency, temporal validity, migration and continuity.
- Assistant replies now enter the extraction projection; repeated bot behavior creates self-impressions and
  the weekly/dream path composes persona only from bot:self artifacts with a stable id.
- Batch merge and lifecycle expiry now use atomic multi-artifact transactions.
- 新增 Source-backed pending 投影与容量治理：旧 `pending.json` 可无损迁移到
  `extraction_state`，重启后按 Source 重建且不再按 200 行静默截断；纯 Governor
  统一输出 normal/pressured/saturated/protective 及抽取、降级、过期清理和告警动作。

- 新增默认开启的本地 BM25 混合召回：标准库字符 bigram、正文/标签倒排索引、
  可见池统计隔离及缓存版本失效；聊天与诊断复用检索器，权重经对照校准为 1.0。
  补充独立验收，配置 `bm25_enabled=false` 可恢复原检索；本次不引入模型、联网检索、数据库迁移或运行依赖。

- WebUI 补充话题队列、抽取策略与 checkpoint 待提交计数；区分记忆主体/说话人及事件时间，直观展示逐条披露级别。
  同步 OpenAPI、生成类型和前后端测试，旧记录缺失信息保持未知。

- 简化 WebUI 日志、路由状态查询、前端筛选/页面状态、Mock 数据及发布资源检查的控制流；
  启用嵌套三元表达式 lint 拦截与正反例验证，保持接口和运行行为不变。

- 同步上游 v0.3.1 的话题缓冲、主体归属和事件时间，适配运行页计数及话题抽取日志，保留取消时缓冲。

- 同步上游 v0.3.0：保留积压触发、WriteOutcome、统一提交、原子 checkpoint 与主体披露判定；
  适配 WebUI 阶段日志和只读诊断，补测无模型配额、会话失败隔离及取消时消息保留。

- WebUI 更新为冷蓝主题：统一浅深色 token、标题区域、统计卡、导航与详情层次；新增语义徽章配色，
  保持 MVVM 和组件适配边界，补充桌面/手机预览，图片继续存放在独立资源分支。

- 合并上游 v0.2.0 Artifact 内核；WebUI 统一使用上游提交、版本与证据链，保留 subject_id。
  抽取按会话选择模型，checkpoint 纳入调度与卸载生命周期，Release 补充 `app/` 运行模块。

- 使用 `z.looseObject()` 替换弃用的 `.passthrough()`，保持头部扩展字段；新增弃用 API 的 lint 拦截。

- 新增 OpenAPI 3.1 管理契约与生成传输类型，连接 Zod、Mock、真实后端响应及 CI 漂移检查；
  生成器独立使用 TS 5 编译器 API，应用保持 TS 7 严格检查，开发依赖不进入发布包。

- 开发与发布说明沿用中文，统一新增代码注释、业务日志和管理提示的语言，保留接口标识及英文版指南。

- 日志新增真实模块/文件/函数/行号、业务阶段、耗时、结构化字段和脱敏异常位置；
  任务 ID 自动贯穿阶段，前端支持级别/模块/业务字段筛选，兼容旧日志。
- 补齐九种记忆类型和诊断命中/空结果预览；预览图片迁至独立资源分支，代码 PR 仅引用图片。

- 新增宿主原生 WebUI：记忆库、运行与任务、召回诊断、生命周期日志；独立 Mock 无需启动 AstrBot。
- 记忆库覆盖六种 Artifact 家族、三种 scope/状态、来源会话筛选、版本/blob、证据与账本。
- 支持 JSON 内容修订、范围调整、遗忘/恢复与旧内容载入；版本冲突检测和账本写入使用同一事务。
- 手动抽取、每周整理和取消与定时任务共用单任务执行器；持久化生命周期、异常中断和脱敏错误。
- 修正抽取失败/取消、会话数量限制和抽取期间新消息的缓冲保留；热重载时清理任务、路由、数据库。
- 默认数据库路径使用 AstrBot 数据目录 API，兼容 Windows 与自定义部署路径。
- 前端采用 TypeScript 7 严格检查、Oxlint、Oxfmt 与 Zod，隔离业务状态和 UI 适配层。
- 工作台筛选与任务确认收敛到 ViewModel；写入后刷新覆盖旧请求，取消操作固定目标任务。
  新增实际 React hook 回归测试及 Oxlint 分层规则的正反向测试，防止视图绕过适配层。
- 新增 Release 打包：发布时构建前端，只分发后端运行文件、静态产物及许可证。
- 安装入口从源码克隆调整为 Release 的 `astrbot_plugin_seekmemory.zip` 附件；
  源码 ZIP/tar.gz 和 Git 克隆保留开发源码，不含前端产物。详见 README 的安装说明。
- 入口映射：原“插件配置”继续用于配置；记忆操作改从“插件卡片 → 插件视图”进入。
  页面与截图见 [WebUI 使用说明](docs/zh/guides/webui.md)。

## 0.4.0 — 2026-10-23

人格与印象的进化改成每天一次的「梦境」；上下文开始有预算。

- **梦境周期（ISSUE-0030）**：白天只把对话写进缓冲，不再抽取、不再修订印象；
  到 `dream_time`（默认 03:30）一次跑完：逐话题抽取 → 遗忘/合并/修订印象 → 沉淀人格
  → 落一条 `dream_runs` 台账。台账主键是日期，当天已完成的直接跳过（幂等）；
  中途失败保留待抽取行，下次从断点续跑。`decide_flush(dream_only=True)` 放在所有
  分支之前，杜绝 0.3.1 里 backlog 绕过白天开关的问题。
- **上下文预算（ISSUE-0031）**：新增 `ContextBudget`（注入字数、系统提示字数、
  群聊流水条数、历史条数）与 token 估算；注入预算有单一来源，面板可见。
  实测语料 248→166 对时人味 3.79→3.77（等价），单轮输入省约 1.5k tokens。
- 面板状态接口新增 `dream` 与 `budget` 两块。
- 测试：新增 `tests/test_dream.py`（12 条），全量 279 条。

## 0.3.1 - 2026-10-21

Topic buffer and attribution hardening.

- Group chat sources continue to be captured and extracted as shared memories.
- Typed DialogueTurn buffer with topic segmentation and 24h TTL trigger.
- Extractor now records subject_kind/subject_id and event_at.
- Artifact created time uses event time with Source timestamp fallback.
- Added validity date normalization and owner-id resolution.

## 0.3.0 - 2026-10-21

Backlog hardening and retrieval boundary.

- Backlog flush ignores the worth_now gate after a quiet window.
- Session-safe draining prevents unprocessed sessions from being dropped.
- All production writes now use CAS commit with versions and audit.
- Checkpoint state events commit atomically with their revision.
- Recall applies subject-aware disclosure before assembly.
- RetrievalCandidate reserves a lexical signal for future BM25.

## 0.2.0 - 2026-10-21

Artifact kernel foundation and online cutover.

- Source is the immutable truth; user and assistant replies are persisted.
- Artifact writes use CAS commits, append-only versions and version-level evidence.
- Added subject_id, state_events, 30-minute checkpoints and universal disclosure.
- Added the ChatModel boundary and wired extraction through the new commit path.

## 0.1.9 — 2026-10-21

说话方式与调用可见性。

- **说话方式**：允许偶尔两三句、也允许两个字；答完顺口问一句。语料 169 → 203 对，
  新增反问/极短/絮叨/自我插入/岔开五类。实测（47 条场景、2 采样）：
  长度标准差 4.2→7.2、反问率 21%→36%、语气词 26%→38%、>25 字比例 0→9%。
- **记忆调用日志**：每轮记一条「唤起档位 / 命中条数 / 注入字数」到
  `plugin_data/seekmemory/calls.jsonl`（不记内容），供监控统计"什么情况下翻记忆"。
- 监控报告新增「记忆调用」一节：none/strict/loose 分布、翻到东西的比例、平均字数。
- 测试 165 → 167。

## 0.1.8 — 2026-10-21

版本链的三处修正，让它真的能用：

- **修订判定改看包含度**：旧印象是新印象的雏形（`contain ≥ 0.45` 且 `dice ≥ 0.3`）就出新版本；
  原来只看 Dice，`他有点倔 → 他有点倔，嘴上不饶人` 会被判定为"不相关"而不修订。
- **并入后退休**：新印象并进旧印象后，刚写的那条标 `merged` 并移出缓存，
  不再出现"同一件事两条印象"。
- **轨迹措辞**：注入里只补「（以前觉得…）」，不再重复现在；时间说人话
  （几天前 / 几周前 / 几个月前）。示例：
  `你印象里他嘴上不饶人，其实是怕麻烦（以前觉得有点倔）。`
- 测试 165 条。

## 0.1.7 — 2026-10-21

把版本链做实：印象改过之后，她知道自己以前怎么想。

- **`versions` 表**：每次落库都留一份（entity + revision + payload blob + 头信息），
  旧 revision 不再被覆盖。
- **`DB.history(id)`**：读一条记忆的版本链（旧→新）。
- **印象轨迹**：同一条印象有 ≥2 版时，注入里会带「（以前觉得…，现在觉得…）」；
  没变过就不显示。
- 测试 162 → 165。

## 0.1.6 — 2026-10-21

把记忆的层级结构定下来：**人格 > 印象 > 记忆 > 事实**。

- **印象分人**：跟谁说话就调出对那个人的印象（`pinned(cache, subject)`）。
  对你说话调对你的印象，对 12345 说话调对 12345 的印象，不混。
- **组装按层级排序**：人格 → 印象（最多 2 条）→ 场景 → 细节 → 事实 → 例子。
  同一层内保持相关性顺序。
- **超预算时按层级砍**：先砍例子，再砍事实、细节、场景——事实最先被牺牲，
  人格与印象最后。
- 测试 157 → 162。

## 0.1.5 — 2026-10-21

群聊记忆改为**按人归属**：群聊本身不是隐私边界（大家都在），所以不按会话隔离，
按说话人归属。

- 群聊记忆写 `scope=shared`、`said_by=<说话人 QQ>`；一个批次有多个说话人时
  payload 记 `speakers` 列表、`said_by=group`。
- 私聊记忆仍是 `private`，只归那个会话。
- 抽取 prompt 明确：群里别人的事正文要写清是谁说的（QQ 或称呼），"他"只指主人。
- **常驻层只放关于主人的印象**（`said_by=owner`）：群里的印象属于某人，
  不能混进她的全局画像。
- 测试 156 → 157。

## 0.1.4 — 2026-10-21

记忆系统开始观察群聊，但严格按群隔离。

- **群聊写入**：新增 `observe_groups`（默认开），群里说的话也进抽取，每条带
  会话归属与说话人；写进去的记忆 `scope=private`，**只在该群可见**，不进私聊、
  不进别的群。
- **按会话抽取**：缓冲按会话切开分别抽（一次最多 6 个会话），避免多个群混成一批
  导致归属丢失。
- **人格不串**：每周人格沉淀只吃主人私聊的印象，群里的印象不会进全局人格。
- 读路径抽成 `recall/pipeline.py`，`main.py` 回到 273 行的插件胶水层。
- 测试 152 → 156。

## 0.1.3 — 2026-10-21

抽取回到"夜间批量为主"，白天只在值得时补一次，控制调用与噪声。

- `idle_flush_seconds` 默认改为 **0**（关闭白天纯空闲抽取），夜间 23:50 批量抽取为主力。
- 白天若要提前抽，需同时满足：攒够 8 条、这批对话里有计划/日期、稳定事实或强情绪
  信号（`perceive.absorb.worth_now`），且每天最多 2 次（`max_flushes_per_day`）。
- 实测单次抽取成本：4 条对话约 617 prompt tokens（384 命中缓存）；120 条约 2705
  （1536 命中）；completion 0~300。夜间一次批量比分多次便宜。
- 测试 147 → 152。

## 0.1.2 — 2026-10-21

打磨"什么时候用记忆"：之前每句话都走一遍检索、印象只增不改。

- **唤起分档（`recall/intent.py`）**：寒暄、问时间、操作类请求 → 不检索，只给常驻层；
  「还记得/上次/我叫什么」与情绪类 → 放宽检索（k+2、阈值 0.3→0.2、预算 ×1.4）；
  其余正常检索。
- **主动浮现（`recall/drift.py`）**：没有线索时按"越近、情绪越强、越重要、越久没提"
  加权偶尔想起一件事；shadow、secret、冷却中的不浮现。
- **印象修订（`maintain/impression.py`）**：新印象和旧印象高度重合时不再堆一条，
  而是改旧印象——同一句只加权重与命中数；换了说法就出新 revision，
  旧版本进 blob 与账本。
- 测试 132 → 147，三基准数字不变。

## 0.1.1 — 2026-10-21

让记忆系统真的被用上：之前抽取只在半夜跑一次，且只抽"印象"，导致生产上长期是空库。

- **抽取口径改为四层**：fact / scene / detail / impression 都要，事实（名字、地点、
  时间、计划、关系）不许漏；条数上限 3 → 6。
- **抽取必须给 tags**：3~6 个中文关键词，供证据闸门使用。此前生产抽取不产标签，
  闸门最有力的一维在真实数据上是空的。
- **空闲抽取**：聊完安静 180 秒、且攒够 4 条，就在后台抽一次，不再等深夜；
  夜间 23:50 仍保留作兜底。两个参数都可配（`idle_flush_seconds` / `min_pending`）。
- **缓冲落盘**：未抽取的对话写到插件数据目录 `pending.json`，容器重启不再丢。
- 抽出 `perceive/buffer.py`、`perceive/absorb.py` 两个模块，`main.py` 回到插件胶水层
  （370 → 267 行）；测试 122 → 132。

## 0.1.0 — 2026-10-21

首个可用版本。作为 AstrBot 插件接入 QQ，记忆链路端到端跑通。

### 记忆

- **Artifact 模型**：10 字段公共头（id / family / revision / state / scope / lineage /
  strength / time / said_by / shareable）+ 类型化 payload；六个 family（memory / example /
  persona / media / secret / designated）；记忆分 fact / scene / detail / impression 四级。
- **遗忘曲线**：`R = e^(−t/S)`，`S` 由基准天数、权重、命中次数、形态、情绪共同决定；
  定时衰减，重要记忆留下、琐事忘掉。
- **检索打分**：字面重合、标签、情绪、权重、新鲜度五维 + 激活扩散，减去近期已用与过热惩罚，
  留 10% 随机探索。大库下走倒排二元组索引，实测 10ms 量级。
- **相关性闸门**：只认相关性证据（字面 / 标签 / 情绪 / 激活），权重与新鲜度只参与排序、
  不能单独让一条记忆过门；不相关就返回空。检索层噪声 81% → 40%。
- **常驻层**：人格与印象层固定注入（38 字/轮），不经过闸门——「你觉得我这个人怎么样」
  这类零字面问题靠它接住。
- **组装**：头（人格 / 印象 / 最相关）/ 中（摘要 / 事实 / 例子）/ 尾（最近两轮），
  按预算裁剪并在标点处截断，防 lost-in-the-middle。
- **写入侧建边**：同 scope 相似度建 similar 边、同日建 temporal 边，出度上限 5，fail-open。
- **人格沉淀**：每周把稳定的 impression 拼成第二人称 persona，旧版本标 merged，写账本。
- **scope 隔离**：private 只给归属会话，shared 全放，shadow 只输出遮蔽句；指定记忆
  三条硬条件（私聊、触发词、未给过）才交付正文。

### 存储与审计

- 内容寻址 blob（sha256）、不可变修订、哈希链账本（`self_hash = sha256(prev + payload)[:16]`）。
- 只有 `store/db.py` 写 SQL；`core/` 不依赖上层；全链路 fail-open。

### 评测

- `run.py` 像人指数 100/100（已饱和，见 ISSUE-0019）、1000 条记忆压缩 850×。
- `scale.py` 8 用户 / 60 天 / 2400 条：每轮 13 字、232×、召回 5/6。
- `ablation.py` 组件消融 + `no_gate` 对照。
- `large_e2e.py` 6 种人格画像 × 180 天 × 31,926 条消息 × 60 题 × 4 策略，固定
  `deepseek-flash` / temperature=0：SeekMemory 命中 49/60、人味 4.27，关键词基线 42/60，
  全量注入 24/60。等效 token 约为全量注入的 1/7，比关键词基线贵 6%。

### 已知限制

- 零字面同义问法召回不了（无 BM25 / 向量检索，见 ISSUE-0001）。
- 静态黄金集已饱和，难任务集待建（ISSUE-0019）。
- 缓冲层、三档不确定措辞、反思接线、容量治理第三级以后仍未完成（ISSUE-0002 / 0015 / 0014 / 0010）。
