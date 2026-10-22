# 贡献指南

> AI agents and external contributors must also read [AGENTS.md](AGENTS.md).

> Developer interfaces: [docs/INTERFACES.md](docs/INTERFACES.md) | [docs/DEV-SETUP.md](docs/DEV-SETUP.md).


> 背景：v0.1 的所有改动都直接进了 `main`，没有 issue、PR 和评审。从这份文件开始，
> P0/P1 改动必须先记录问题，再在分支上修，最后走 PR 流程合并。
>
> 当前 GitHub CLI 未登录，`docs/issues/` 是 issue/PR 的本地事实源；登录后按文末
> 「同步到 GitHub」补齐远端，本地编号继续作为主键。

## 问题分级

| 级别 | 定义 | 流程 |
|---|---|---|
| P0 严重 | 数据损坏、隐私泄漏、崩溃 | 立即开 ISSUE → 独立分支 → PR → 合并 |
| P1 重要 | 功能失效、性能退化 | 开 ISSUE → 分支 → PR |
| P2 一般 | 体验、文档 | 可直接提交，PR 里说明 |

补充约定：

- **P0** 允许先开分支止血，但必须在 24 小时内补 `docs/issues/ISSUE-XXXX.md`，并在 PR 里
  写清止血范围和后续完整修复。
- **P1** 不允许"顺手改"：先有 issue，再有分支。拿不准级别时按更高一级处理。
- **P2** 直接提交 `main` 时，在 commit 正文写清影响面；如果同一批还有 P0/P1 改动，
  必须在 PR 描述里列出。
- 级别可以升级/降级，但要在 issue 的「决策记录」里写日期和理由。

## 流程

1. `docs/issues/ISSUE-XXXX.md` 用 [ISSUE 模板](docs/issues/TEMPLATE-ISSUE.md) 记录问题（症状/复现/影响面/建议方案）
2. `git switch -c fix/issue-XXXX-short-name`
3. 修 + 补测试
4. 按 [PR 模板](docs/issues/TEMPLATE-PR.md) 写 `docs/issues/PR-XXXX.md`（改动摘要/验证方式/风险）
5. `git switch main && git merge --no-ff fix/...`
6. 合并后把 issue 状态改为 closed

> 本地阶段没有 GitHub PR，`docs/issues/PR-XXXX.md` 就是 PR 本体：描述、验证、风险、
> 评审记录都写在这里，并在修复分支上随代码一起提交；合并后归档。

### 编号与命名

- issue 编号全局递增、不复用：`ISSUE-0001`、`ISSUE-0002`……补零到四位。
- PR 文件编号跟随主 issue：`PR-0001.md` 对应 `ISSUE-0001`。一个 PR 关多个 issue 时，
  取主 issue 的编号，正文里列出全部关联 issue。
- 分支名：`fix/issue-0001-paraphrase-recall`、`feat/embedding-index`、`docs/contributing`、
  `test/...`、`bench/...`、`ci/...`、`refactor/...`。分支名用小写和连字符。
- 一个分支只做一件事；格式化、重命名、依赖升级等无关改动拆到单独分支。

### PR 文件的最低要求

- **关联 issue 编号**：P0/P1 改动没有 issue 不允许合并。
- **改动摘要**：改了哪些文件、为什么改、明确没改什么。
- **验证方式**：跑了什么命令、结果如何。检索/打分相关必须附 benchmark 前后对比，
  数字要能追溯到 `benchmarks/results/` 或 PR 里贴出的命令输出。
- **风险与回滚**：影响哪些调用方、配置是否兼容、怎么回滚。
- **评审记录**：本地阶段至少一名评审人（可以是另一个 agent）在 PR 文件末尾写结论；
  单人项目写自审清单并注明"自审"。

### 合并

```bash
git switch main
git pull --ff-only                       # 有远端时
git merge --no-ff fix/issue-0001-paraphrase-recall
git push origin main                     # 有远端时
```

- 必须用 `--no-ff`，保留"这个改动是一个整体"的合并点。
- 合并后：issue 状态改 `closed`，补 merge commit hash；PR 文件状态改 `merged`。
- 回滚用 `git revert -m 1 <merge-commit>`；不要 `reset --hard` 已推送的 `main`。
- 本地阶段不强制建 tag；发版时再在 `main` 上打 `vX.Y.Z`。

## 提交规范

`type(scope): 摘要`，type ∈ feat/fix/docs/test/bench/refactor/ci

- 摘要用中文，动词开头，不超过 50 字，句末不加句号。
- scope 用模块名：`recall`、`store`、`core`、`perceive`、`maintain`、`bench`、`ci`、`docs`。
- 正文写"为什么"和"影响面"，不要只写"改了什么"。
- 一个 commit 一件事；不要用 `update`、`fix bug`、`修改` 这类无信息摘要。
- 示例：

  ```
  fix(recall): 零字面重合时不再用 weight 先验伪装召回

  关联 ISSUE-0001。seeds 为空时 select 仍返回 top-k，导致无关高权重
  记忆被注入；改为记录 zero_signal 并返回空，等混合检索方案落地。
  ```

## 测试与基准

提交前至少跑：

```bash
for f in tests/test_*.py; do python3 "$f"; done
python3 benchmarks/run.py
```

- 改 `recall/` 或打分：加跑 `python3 benchmarks/scale.py`，把 `scale.md` 的关键数字
  与 `main` 对比写进 PR。
- 改端到端策略/提示词：加跑 `python3 benchmarks/e2e.py`（需要模型 API），只把它当趋势，
  不作硬门槛。
- 新功能必须有测试；修 bug 必须先写能复现的测试，再改实现。
- 不许为了让测试通过而改测试预期；确需改，在 PR 里单独说明原因。
- CI 的 Python 版本是 3.10/3.11/3.12；本地也尽量用 3.10+ 跑一遍。

## 文档

- 改目录、依赖方向、调用链：同步 `docs/INDEX.md`、`docs/DESIGN.md`、`docs/CONTRACT.md`。
- 新增模块或 README：保证从 `docs/INDEX.md` 能点到。
- issue/PR 文件只追加，不改历史记录；纠错用「补充」小节并写日期。

## 同步到 GitHub（gh 登录后）

先确认远端和登录状态：

```bash
git remote -v
gh auth status
```

然后按"先 issue、后 PR"的顺序同步：

```bash
# 1. 同步 issue；标签按级别选 P0/P1/P2
gh issue create --title "..." --body-file docs/issues/ISSUE-0001.md --label P1

# 2. 推送分支，用本地 PR 文件作为描述
git push -u origin fix/issue-0001-paraphrase-recall
gh pr create --base main --head fix/issue-0001-paraphrase-recall \
  --title "..." --body-file docs/issues/PR-0001.md
```

- GitHub 会自动分配 issue/PR 号，和本地编号不一定一致；在本地文件顶部加一行
  `GitHub: #123`，本地编号继续作为主键。
- 同步后，GitHub 的 review/CI 结论回写到 PR 文件的「评审记录」。
- 在 gh 登录前，不要为了"先占号"去创建空 issue；本地文件就是正式记录。

<a id="release-packaging"></a>

## 发布打包

`.github/workflows/release.yml` 在 PR 和手动触发时构建、测试可安装的分发包，
上传包含插件 ZIP 和校验文件的 Actions 构件，保留七天；这两种触发方式不创建 Release。

评审合并后的发布步骤：

1. 在短期分支 `release/X.Y.Z` 更新 `metadata.yaml` 和 `CHANGELOG.md`，评审并合并后再打标签。
2. 在已评审的提交上推送 `vX.Y.Z` 标签。标签必须与 metadata 版本完全一致，支持 `1.2.3-rc.1` 等预发布版本。
3. CI 按锁文件安装前端依赖，执行严格前端检查和 Python 测试，构建生产资源，按运行文件白名单打包。
4. 独立任务使用已有标签发布 `astrbot_plugin_seekmemory.zip` 和 `SHA256SUMS`。
   预发布标签对应预发布版本；已有 Release 不会被覆盖，重复发布会失败，需检查原因。

安装包包含 Git 跟踪的 `app`、`core`、`store`、`recall`、`perceive`、`maintain`、`webui` 下的 `.py`，
以及 `main.py`、元数据、配置定义、`store/schema.sql`、许可证和 `pages/memory` 生产资源。
新增运行资源或包时，应同步修改 `scripts/package_plugin.py` 和打包测试。
构建产物不提交到 Git，源码归档保持源码形态。后端无需编译，分发 `.py` 以保持 Python 和平台兼容性。

本地打包使用根目录 README 中的构建命令。先运行 `python -m pip install -r requirements-dev.txt`
安装仅供开发使用的契约测试依赖。发布前运行
`python -m unittest discover -s tests -p 'test_*.py'` 和 `python tests/test_smoke.py`。
打包测试会解压 ZIP，在独立 Python 进程中执行后端冒烟测试。

安装了兼容宿主时，`tests/test_webui_host.py` 还会验证真实 AstrBot 请求上下文和插件生命周期。
独立 CI 跳过这些宿主专用测试；存储、scope、修订和任务测试无需 AstrBot。
测试不会启动消息适配器或调用付费模型。修改 API 时先更新 `openapi.yaml`，运行
`cd dashboard && pnpm generate:api`，再同步 Zod 校验、桥接适配器和实现测试。
`pnpm check` 检查生成类型是否过期，随后执行 TS 7、lint、Mock 契约和格式检查。
真实响应的跨语言验证在插件根目录执行：

```bash
python tests/test_api_contract.py --export dashboard/node_modules/.tmp/backend-contract.json
pnpm --dir dashboard test:contract
```

该步骤执行真实路由、数据库、修订、诊断与任务代码，仅替代宿主传输对象；缺少导出的响应会使前端检查失败。
已安装 AstrBot 时，宿主集成测试还会对实际 `JSONResponse` 执行同一契约校验。
CI 与发布构建均执行这些检查；契约、生成工具、测试依赖与临时响应不进入安装包。

安装使用 Release 附件。若希望通过自定义插件源自动安装或更新，应将该源的 `download_url`
指向 Release 附件地址；仅填写仓库地址不会自动选择发布附件。

## 可读性检查

- 优先提前返回/跳过，避免有效路径层层缩进；异常处理范围只覆盖可能失败的步骤。
- 多步骤操作使用有意义的中间变量，避免把异步请求、校验和取值挤在同一个表达式中。
- 多分支用 if/switch，固定文案和样式用映射；前端嵌套三元表达式由 Oxlint 拦截。
- 只在明显重复或主函数过长、职责被打断时提取完整操作，避免碎片化辅助函数。
- 重构保留接口、错误处理和状态时序，通过相关行为/契约测试验证；格式化工具不能代替可读性审查。

## 参考

- 目录与调用链：[docs/INDEX.md](docs/INDEX.md)
- 设计规格：[docs/DESIGN.md](docs/DESIGN.md)
- 模块契约：[docs/CONTRACT.md](docs/CONTRACT.md)
- 第一个 issue（范例）：[docs/issues/ISSUE-0001.md](docs/issues/ISSUE-0001.md)
