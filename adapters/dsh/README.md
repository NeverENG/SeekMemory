# dsh-seekmemory

把 [SeekMemory](https://github.com/NeverENG/SeekMemory) 的记忆内核接到 DeepSeek Harness（DSH）的宿主适配器。

内核留在 Python 侧、以本机 loopback 契约对外；这个包只做协议桥：**捕获 → 召回 → 人格**，内核不可达时整体 fail-open（对话不受影响）。

背景与取舍见工作区里的两份文档：

- `../SeekMemory-DSH-适配方案-v2.md`（契约、里程碑、G1–G14 普适性清单）
- `../SeekMemory-DSH-适配案例复盘.md`（13 类真实坑，以及它们各自改了什么）

上游接口 issue：https://github.com/NeverENG/SeekMemory/issues/107

---

## 当前状态

| 项 | 状态 |
|---|---|
| M3 适配器骨架 | ✅ 完成，跑在 mock 内核上 |
| M4 注入打通 | ✅ 已于 2026-10-27 在隔离实例（独立 `DSH_HOME` + headless/web）真机验证：加载、apply、3 个钩子、卸载回收全部走通 |
| M5 抽取归宿主 | ❌ 未做（`/extract/plan` 客户端已就绪，未接 `callLLM`） |
| 契约文档 / conformance 层 | 在 issue #107 里，等 Lead 定范围 |

**已装进 `web` profile，但还没在真实宿主里跑过。** 安装方式见 `tools/install-profile.mjs`（link: + junction，不碰 pnpm）：

```
dependencies.dsh-seekmemory = link:D:/1gzq/dsh-seekmemory
dsh.profile.bundles += dsh-seekmemory
```

- 备份：`D:\1gzq\backup\profile-web-<时间戳>\package.json`
- 回滚：双击 `D:\1gzq\rollback-web.cmd`（纯 ASCII，恢复 package.json + 删 junction）
- `desktop` profile **一个字没动**，本会话就活在那上面

⚠️ 别对这个 profile 跑 `pnpm install`——会把 junction 冲掉，改用 `tools/install-profile.mjs` 重装。

---

## 目录

```
src/index.js          入口：name / inject / apply（绝不抛）
src/safe-mode.js      启动跳闸：boot.json（启动阶段）+ crash.json（运行期未捕获异常）
src/host-dsh.js       唯一的 DSH 特定文件：4 个扩展点都在这里（G12）
src/kernel-client.js  契约客户端：7 个端点，永不抛，降级原因是枚举（G14）
src/config.js         默认值与归一化（刻意不依赖 schemastery）
src/message.js        createUserMessage 动态导入 + 手工兜底

mock/kernel.mjs       M0 mock 内核：契约的可执行样例，含故障注入开关
scripts/check-manifest.mjs   G13/G4 静态检查（无值导入、无 nullable、闸门写法）
scripts/smoke-contract.mjs   契约冒烟（9 项）
test/client-failopen.mjs     fail-open 八种降级（11 项）
test/hooks-fake-host.mjs     假宿主验 apply/注入/卸载（19 项）
test/safe-mode.mjs           跳闸/强杀豁免/自愈/开关键（42 项）
```

## 怎么跑

```bash
# 1. 静态检查（G13/G4）
node scripts/check-manifest.mjs

# 2. 单元测试（不需要内核）
node test/client-failopen.mjs
node test/hooks-fake-host.mjs

# 3. 契约冒烟：先起 mock，再打
node mock/kernel.mjs --data-dir .tmp/mock          # 另开一个终端
node scripts/smoke-contract.mjs --runtime .tmp/mock/runtime.json
```

`npm run verify` = 上面第 1、2 步。

mock 的故障注入开关（验 fail-open 用）：

| 环境变量 | 效果 |
|---|---|
| `MOCK_DELAY_MS=5000` | `/recall` 变慢 → 触发 timeout |
| `MOCK_FAIL=500` | `/recall` 直接 500 |
| `MOCK_EMPTY=1` | `/recall` 返回空块 |
| `MOCK_BAD_CONTRACT=9` | `/healthz` 报别的契约版本 → contract_mismatch |
| `MOCK_PLAN=1` | `/extract/plan` 给一个假任务而不是 204 |

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
| `safeModeAfterFailures` | `1` | 启动阶段连续几次没走完就跳闸（1–10） |
| `safeModeAutoRetry` | `3` | 安全模式里连续几次启动后自动重试一次（0 = 永不） |

## 已知偏离与待办（诚实清单）

1. **用 ESM JS，不是 TypeScript。** 本机没有 `tsc`/`esbuild`，且沙箱里 spawn 子进程不可靠（`spawn EPERM`）。为了"现在能真跑"，先写 JS；文件边界已按 G12 隔离，工具链就绪后按文件逐个迁 TS 不影响结构。
2. **值导入了宿主符号 `createUserMessage`——但走的是动态 `import()`。** 静态值导入是 G13 明令禁止的（符号被删会让整棵插件树崩），所以改成在 `apply()` 内 `await import('@deepseek-ai/dsh-llm')`，失败就走手工兜底形状并打日志。**兜底路径没有在真宿主上验过**。
3. **没有导出 schemastery 的 `Config`。** 同上：静态依赖宿主包有加载期风险，先手工校验。
4. **主体键的 `auto` 模式没有真实样本。** 代码会依次试 `session.subjectKey / umo / ownerUmo / meta.*`，全都没有就退 `local:single:default` 并告警——真实 DSH 会话里到底有没有这些字段，**必须实测**（这是 M3 的验收项之一）。
5. **插件能否 spawn python 未验证**，本包也**不依赖**这件事：内核由用户双击或 MCP 拉起，适配器只连 loopback。
6. **模块导入期失败不跳闸（设计取舍）。** 如果 `src/*.js` 本身导入失败（文件缺失、语法错），`apply` 根本不会执行，写不下任何标记——宿主只会打一条 `warning: 1 entry did not activate` 然后正常启动，插件静默缺席。这类失败本质是"代码坏了"，安全模式也没有修复对象，因此不做运行时兜底（把 `apply` 改成 `await import()` 会改变钩子注册时序）。**发布前必须跑真机 import 冒烟**：

   ```powershell
   node --input-type=module -e "import('file:///D:/1gzq/dsh-seekmemory/src/index.js').then(()=>console.log('ok'))"
   ```

   再加一次 `--dump-config` 确认 bundle 真被纳入。

## 许可

MIT。内核侧遵循上游的 MIT / Apache-2.0 双许可。
