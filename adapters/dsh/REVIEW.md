# 给审查者的导读（dsh-seekmemory 0.0.1）

这是一个 **DSH 宿主侧插件**，配合 SeekMemory 内核使用。它随本仓库维护，位于 `adapters/dsh/`，作为独立 npm 包发布，不进入 AstrBot Python 插件 ZIP。

- 上游 issue：https://github.com/NeverENG/SeekMemory/issues/107
- 真机验证结论评论：https://github.com/NeverENG/SeekMemory/issues/107#issuecomment-6431091970

## 它做什么

把内核（Python）当作本机 loopback 服务，插件只做协议桥：

```
DSH 插件                              内核（Python）
  session/event  ──► POST /capture    ──► 写 Source
  agent/pre-step ──► POST /recall     ──► 本地 BM25 + 披露，0 次模型调用
  GET /extract/plan ◄─ 取任务
  宿主 ctx.llm.stream ──► 调模型      （凭据和记账都留在宿主）
  POST /extract/commit ──►            ──► 501 未实现（不能宣称全链路抽取成功）
```

内核不持密钥、不反向开端口、不在事务里发网络请求。

## 先看这三个文件

| 文件 | 看什么 |
|---|---|
| `src/host-dsh.js` | 唯一碰 DSH API 的地方（G12 隔离）；`decision` 用展开而不是重建，保留宿主字段 |
| `src/kernel-client.js` | 永不抛；降级原因是**枚举**而不是布尔（`no_runtime_file`/`timeout`/`contract_mismatch`…） |
| `src/safe-mode.js` | 跳闸判定链：只认 `crash.json`（未捕获异常），pending 只覆盖启动阶段，强杀单次宽容 |

## 怎么跑（不需要内核）

```powershell
cd adapters/dsh
node scripts/check-manifest.mjs      # 静态 7 项（engines/peer/import/nullable/bundle patch…）
node test/client-failopen.mjs        # 11 项：8 种降级原因可区分
node test/hooks-fake-host.mjs        # 19 项：apply 不抛、注入、fail-open、卸载回收
node test/persona-isolation.mjs      # 6 项：多主体画像隔离
node test/safe-mode.mjs              # 42 项：跳闸/强杀/自愈/FORCE/日志隐私
node test/extract-bridge.mjs         # 18 项：抽取桥，block-end 权威/中止/抛错
node test/postinstall-check.mjs      # 7 项：跨平台安装自检（沙箱内 3 项 SKIP）
node test/install-profile.mjs        # 11 项：junction 全新/重复/换目录/实体目录
node scripts/build-check.mjs         # files/入口/bundle patch
```

冒烟（要先起 mock）：

```powershell
node mock/kernel.mjs --data-dir .tmp/mock
node scripts/smoke-contract.mjs --runtime .tmp/mock/runtime.json   # 11 项
```

装到某个 profile 后核对装配（零风险）：

```powershell
scripts\postinstall-check.cmd web <一个隔离 DSH_HOME>
```

## 已验证 / 未验证

**已验证**：114 项单元（11 + 19 + 6 + 42 + 18 + 7 + 11）+ 11 项冒烟 + manifest/build/package 检查；真机四场景（正常失败 / 运行期崩溃 / 强杀 / 安全模式自愈）在隔离 `DSH_HOME` 下跑通；钩子真实触发（pre-step 召回、session 事件捕获）且卸载后全部回收。

**未验证**：真实消息平台下的召回质量；真实模型下的抽取成功率（缺凭据，只验证了 `not_configured` 降级路径）。

## 两个需要上游决定的取舍

1. **主体键**：真实会话里没有稳定标识，我们退化为固定键 + `owner_only`。契约是否把它定为**必须实现**项？
2. **崩溃检测口径**：我们用「未捕获异常 → `crash.json`」。若上游 kernel 也要启动标记，建议同一口径，别用退出码。

## 已知取舍（不做的事）

- 导入期失败不跳闸（安全模式修不了坏代码）；替代方案是发布前 import 冒烟 + `dump-config` 自检。
- 安全模式自愈**不封顶**（按开发者意图），永久坏的插件会周期性崩溃一次。
- 内核侧 `adapters/loopback/` 通过 `scripts/serve.py` 启动；`/extract/plan` 和 `/extract/commit` 已提供拉取任务与写回；但没有真实模型执行的冒烟检查仍报告召回 INCOMPLETE，不能作为完整端到端抽取验收。
