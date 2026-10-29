# dsh-seekmemory

把 [SeekMemory](https://github.com/NeverENG/SeekMemory) 的记忆内核接到 DeepSeek Harness（DSH）的宿主适配器。

内核留在 Python 侧、以本机 loopback 契约对外；这个包只做协议桥：**捕获 → 召回 → 人格**，内核不可达时整体 fail-open（对话不受影响）。

## 归属（ownership）

本适配器**随本仓库维护**，位于 `adapters/dsh/`，与 `adapters/` 下的 AstrBot 适配器并列，是同一个内核的第二个宿主；不是仓库之外的第三方包。

- 只依赖 `app/ports.py` 的端口语义，不 import 内核内部实现；
- 不改动任何内核 Python 代码，全部 diff 落在 `adapters/dsh/`；
- 若维护者决定迁到独立仓库，这个目录可以整体删除，内核与 AstrBot 路径不受影响。

契约讨论见 issue [#107](https://github.com/NeverENG/SeekMemory/issues/107)；两个适配器的分工见 [`adapters/README.md`](../README.md)。

---

## 当前状态

| 项 | 状态 |
|---|---|
| M3 适配器骨架 | ✅ 完成（mock 内核 + 真机加载） |
| M4 注入打通 | ✅ 2026-10-27 在隔离实例（独立 `DSH_HOME` + headless/web）真机验证：加载、apply、3 个钩子、卸载回收全部走通 |
| M5 抽取归宿主 | ✅ 已实现，**默认关闭**：`extractEnabled: false`，且必须显式配 `llmProvider` / `llmModel` 才会拉活 |
| 契约文档 / conformance 层 | #107 已通过 #113 合入，见中英文模块文档及 `--layer conformance` |
| 运行时协议桥 | 已实现客户端、模拟服务与真实 `scripts/runtime_http.py` 的 Python AgentRuntime 集成测试 |

说明：M4 的"真机"指真实 DSH 宿主进程；`test/runtime-python-smoke.mjs` 会启动 `scripts/runtime_http.py`，让 RuntimeBridge 驱动真实 Python `AgentRuntime`，不再只依赖 mock 内核。

---

## 目录

```
src/index.js          入口：name / inject / apply（绝不抛）
src/safe-mode.js      启动跳闸：boot.json（启动阶段）+ crash.json（运行期未捕获异常）
src/host-dsh.js       唯一的 DSH 特定文件：4 个扩展点都在这里（G12）
src/kernel-client.js  记忆及运行时契约客户端，复用本机认证连接与固定降级原因
src/runtime-bridge.js 运行时 JSON 映射、能力识别与卸载取消，不含策略或模型循环
src/extract-bridge.js M5 拉取式抽取：/extract/plan → 宿主 LLM → /extract/commit
src/config.js         默认值与归一化（刻意不依赖 schemastery）
src/message.js        createUserMessage 动态导入 + 手工兜底

mock/kernel.mjs       M0 mock 内核：契约的可执行样例，含故障注入开关
scripts/check-manifest.mjs   G13/G4 静态检查（无值导入、无 nullable、闸门写法）
scripts/build-check.mjs      打包白名单自检（files / 入口 / dsh.bundle.patch）
scripts/postinstall-check.mjs 跨平台安装后自检（node 版；.cmd 是 Windows 包装）
scripts/smoke-contract.mjs   契约冒烟（11 项）
scripts/check-kernel-contract.mjs  内核端点契约符合性（15 项，对任意 serve.py 都能跑）
test/client-failopen.mjs     fail-open 八种降级（11 项）
test/hooks-fake-host.mjs     假宿主验 apply/注入/卸载（19 项）
test/persona-isolation.mjs   双主体画像隔离：A 的画像不得出现在 B 的上下文（6 项）
test/safe-mode.mjs           跳闸/强杀豁免/自愈/开关键（42 项）
test/extract-bridge.mjs      抽取桥（18 项：block-end 权威 / 中止 / 抛错 / 无 llm 服务）
test/postinstall-check.mjs   自检脚本用例（dump 判定 + 子进程路径）
test/install-profile.mjs     安装器 junction 四场景（全新 / 重复 / 换目录 / 实体目录）
```

## 怎么跑

```bash
# 1. 静态检查（G13/G4）
node scripts/check-manifest.mjs

# 2. 单元测试（不需要内核）
node test/client-failopen.mjs
node test/hooks-fake-host.mjs
node test/persona-isolation.mjs
node test/safe-mode.mjs
node test/extract-bridge.mjs
node test/postinstall-check.mjs
node test/install-profile.mjs
node test/runtime-python-smoke.mjs

# 3. 打包白名单自检
node scripts/build-check.mjs

# 4. 契约冒烟：先起 mock，再打
node mock/kernel.mjs --data-dir .tmp/mock          # 另开一个终端
node scripts/smoke-contract.mjs --runtime .tmp/mock/runtime.json
node scripts/check-kernel-contract.mjs --runtime .tmp/mock/runtime.json
```

`npm run lint` = 第 1 步；`npm run test` = 第 2 步；`npm run build` = 第 3 步；第 4 步的两个脚本分别对应 `npm run smoke` 与 `npm run contract:kernel`。

`check-kernel-contract.mjs` 验的是**内核是否符合契约**（/healthz、/capture、/recall、/persona、/status、/extract/plan、/extract/commit 七端点 + 错 token 401 + 未知路径 404），所以对端可以是 mock，也可以是真正的 `serve.py`——后者上线时它就是第一道验收。
CI 由仓库的 `.github/workflows/node-adapter.yml` 承担：单个 `node-adapter` job，按顺序跑语法与 manifest 检查、全部测试套件、`npm pack --dry-run` 与 mock 内核冒烟。

mock 的故障注入开关（验 fail-open 用）：

| 环境变量 | 效果 |
|---|---|
| `MOCK_DELAY_MS=5000` | `/recall` 变慢 → 触发 timeout |
| `MOCK_FAIL=500` | `/recall` 直接 500 |
| `MOCK_EMPTY=1` | `/recall` 返回空块 |
| `MOCK_BAD_CONTRACT=9` | `/healthz` 报别的契约版本 → contract_mismatch |
| `MOCK_PLAN=1` | `/extract/plan` 给一个假任务而不是 204 |

## 安装到某个 DSH profile

必须显式给出本包目录（不内置任何默认路径）：

```bash
node tools/install-profile.mjs --profile <profile> --plugin <path-to-this-package>
```

它做三件事：`dependencies` 加 `link:`、`dsh.profile.bundles` 加条目、`node_modules` 建 junction；改之前把 `package.json` 备份到系统临时目录，并生成 `rollback-<profile>.cmd`。

- 备份与回滚脚本默认落在系统临时目录，可用 `--backup-dir` / `--rollback-dir` 指定；
- ⚠️ 不要对目标 profile 跑 `pnpm install`——会把 junction 冲掉，重跑本工具即可；
- 装完自检（跨平台，推荐）：

  ```bash
  node scripts/postinstall-check.mjs --dsh-exe "/path/to/DeepSeek Harness" --profile <profile> --home <isolated-dsh-home>
  # 只校验已有的 dump（不需要 DSH 安装）：
  node scripts/postinstall-check.mjs --dump <dump.yml>
  ```

  Windows 上也可以用包装脚本：先 `set DSH_EXE_OVERRIDE=C:\path\to\DeepSeek Harness.exe`，再跑 `scripts\postinstall-check.cmd <profile> <home>`（两者行为一致，`--dump` 分支已由 `test/postinstall-check.mjs` 覆盖）。

## 启动跳闸与恢复（崩了也能起来）

两个独立状态文件，都在 `stateDir`（默认与日志同目录）：

| 文件 | 什么时候写 | 什么时候清 | 作用 |
|---|---|---|---|
| `boot.json` | apply 开始写 `pending:true`；**apply 走完立刻**写 `pending:false` | 每次启动覆盖 | 只覆盖**启动阶段**（几十毫秒） |
| `crash.json` | 运行期出现未捕获异常时同步写（含 message / stack / pid / 时间） | 跳闸判定后删除 | 运行期崩溃信号，不依赖退出码、不依赖 exit 事件 |

判定要点（完整逻辑见 `src/safe-mode.js`）：

- **强杀不跳闸**：任务管理器结束、关窗口、断电都不留 `pending`（apply 早就清了），不会误判。
- **单次遗留不跳闸**：只有"启动阶段连续 3 次没走完"才判崩溃；首次安装就没走完则立即跳闸。
- **运行期崩过一次就跳闸**：下次启动进安全模式，一个钩子都不注册，宿主照常可用。
- **安全模式可自愈**：连续 3 次启动后自动重试一次（`safeModeAutoRetry`，0 = 关闭）。

恢复：

```powershell
# 立即解除（下次启动生效）
$env:SEEKMEMORY_FORCE = '1'

# 或者直接删状态文件
Remove-Item "$env:DSH_HOME\seekmemory-logs\boot.json","$env:DSH_HOME\seekmemory-logs\crash.json" -Force

# 彻底禁用（一个钩子都不注册）
$env:SEEKMEMORY_DISABLE = '1'
```

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `enabled` | `true` | 总开关，关掉不注册任何钩子 |
| `runtimePath` / `dataDir` | 空 | `runtime.json` 路径；`dataDir` 用来推导它 |
| `hostContract` | `1` | 期望契约版本，不符即拒绝注入并报 `contract_mismatch` |
| `recallTimeoutMs` | `800` | 召回预算，超时当本轮没记忆 |
| `captureTimeoutMs` | `300` | 捕获预算，失败只记日志 |
| `budgetChars` | `600` | 每轮注入字符上限 |
| `k` | `8` | 每轮最多几条 |
| `subjectKey` / `subjectMode` | 空 / `auto` | 主体键；`auto` 取会话元数据，取不到退固定键并**告警一次** |
| `injectRecall` / `injectPersona` | `true` | 可只捕获不注入（与别的记忆插件共存的过渡期用） |
| `extractEnabled` | `false` | 抽取循环开关；开之前必须先配下面两项 |
| `llmProvider` / `llmModel` | 空 | 抽取用的宿主侧模型；留空则跳过并记原因，**绝不猜宿主默认模型** |
| `safeModeAfterFailures` | `1` | 启动阶段连续几次没走完就跳闸（1–10） |
| `safeModeAutoRetry` | `3` | 安全模式里连续几次启动后自动重试一次（0 = 永不） |

## 已知偏离与待办（诚实清单）

1. **用 ESM JS，不是 TypeScript。** 文件边界已按 G12 隔离，工具链就绪后可按文件逐个迁 TS，不影响结构。
2. **值导入了宿主符号 `createUserMessage`——但走的是动态 `import()`。** 静态值导入是 G13 明令禁止的（符号被删会让整棵插件树崩），所以改成在 `apply()` 内 `await import()`，失败就走手工兜底形状并打日志。兜底路径已在 `test/hooks-fake-host.mjs` 覆盖，尚未在真实宿主上命中过。
3. **没有导出 schemastery 的 `Config`。** 同上：静态依赖宿主包有加载期风险，先手工校验。
4. **主体键的 `auto` 模式没有真实样本。** 代码会依次试 `session.subjectKey / umo / ownerUmo / meta.*`，全都没有就退 `local:single:default` 并告警——真实 DSH 会话里到底有没有这些字段，**必须实测**。真机结论（无稳定主体键 → 退固定键）已写进 issue #107 的评论。
5. **插件不 spawn Python。** 内核由用户或 MCP 拉起，适配器只连 loopback；因此"内核没起"是常态，按 fail-open 处理。
6. **模块导入期失败不跳闸（设计取舍）。** 如果 `src/*.js` 本身导入失败（文件缺失、语法错），`apply` 根本不会执行，写不下任何标记——宿主只会打一条 `warning: 1 entry did not activate` 然后正常启动，插件静默缺席。这类失败本质是"代码坏了"，安全模式也没有修复对象，因此不做运行时兜底。**发布前必须跑真机 import 冒烟**：

   ```bash
   node --input-type=module -e "import('file:///<path-to-this-package>/src/index.js').then(()=>console.log('ok'))"
   ```

   再加一次 `--dump-config` 确认 bundle 真被纳入。
7. **CI 覆盖 Node 侧与真实 Python loopback 联调。** 仓库的 `.github/workflows/node-adapter.yml` 在检测到 `adapters/dsh/` 时跑完整检查（语法与 manifest、全部测试套件、打包白名单、mock contract 与真实 Python `AgentRuntime` 的 loopback 测试）；Python 侧主 CI 不受影响。

## 许可

MIT。内核侧遵循上游的 MIT / Apache-2.0 双许可。

平台适配器接入契约见 [`PLATFORM-CONTRACT.md`](PLATFORM-CONTRACT.md)：平台插件实现 `PlatformAdapter`，通过 `host-bridge` 调用 Runtime；HostBridge 不注册全局 hook。
