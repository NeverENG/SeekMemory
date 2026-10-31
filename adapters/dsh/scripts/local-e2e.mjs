#!/usr/bin/env node
/**
 * 本地端到端：起一个隔离的 DSH，让它连上指定的内核，然后抓证据出结论。
 *
 * 用途：
 *   内核（mock 或真 serve.py）已经起好并写出了 runtime.json，想验证
 *   「DSH 宿主 → 适配器 → 内核」这条链路到底通没通。
 *
 * 和另外两个脚本的关系：
 *   check-kernel-contract.mjs  验内核是否符合端点契约（15 项）
 *   smoke-contract.mjs         验适配器与内核的通路（11 项）
 *   本脚本                      验**真实宿主里**整条链路，并顺带把上面两个跑掉
 *
 * 必须在普通终端里手动运行（沙箱内起不了 Electron 进程），例如：
 *
 *   # 1. 先起内核（任选其一）
 *   node mock/kernel.mjs --data-dir D:\1gzq\e2e\kernel
 *   python -m seekmemory.serve --data-dir D:\1gzq\e2e\kernel
 *
 *   # 2. 一条命令验完整链路
 *   node scripts/local-e2e.mjs ^
 *     --home D:\1gzq\dsh-test-home ^
 *     --runtime D:\1gzq\e2e\kernel\runtime.json ^
 *     --dsh-exe "F:\1\111\DeepSeek Harness.exe"
 *
 * 参数：
 *   --home       隔离的 DSH_HOME（必填，绝不指向 ~/.dsh）
 *   --runtime    内核写出的 runtime.json（必填）
 *   --dsh-exe    DSH 可执行体（必填）
 *   --profile    默认 headless
 *   --task       默认 "记一下：我在准备面试"（会真实走一轮 agent loop，触发 pre-step 与 session/event）
 *   --timeout-ms 默认 120000
 *
 * 退出码：0 全部通过；1 有失败项；2 参数/环境问题。
 */

import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync, copyFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const argv = process.argv.slice(2);
const arg = (name, fallback = '') => {
  const i = argv.indexOf(name);
  return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
};

// 脚本自身的目录：不依赖调用方的 cwd，否则从仓库根跑就找不到同目录的契约脚本。
const HERE = path.dirname(fileURLToPath(import.meta.url));

const home = arg('--home');
const runtimePath = arg('--runtime');
const dshExe = arg('--dsh-exe');
const profile = arg('--profile', 'headless');
const task = arg('--task', '记一下：我在准备面试');
const timeoutMs = Number(arg('--timeout-ms', '120000'));

if (!home || !runtimePath || !dshExe) {
  console.error('用法: node scripts/local-e2e.mjs --home <DSH_HOME> --runtime <runtime.json> --dsh-exe <DSH exe>');
  process.exit(2);
}
if (!existsSync(runtimePath)) {
  console.error(`FAIL  runtime.json 不存在: ${runtimePath}（内核起了吗？）`);
  process.exit(2);
}
if (!existsSync(dshExe)) {
  console.error(`FAIL  DSH 可执行体不存在: ${dshExe}`);
  process.exit(2);
}
if (path.resolve(home).toLowerCase() === path.resolve(process.env.USERPROFILE ?? '', '.dsh').toLowerCase()) {
  console.error('FAIL  --home 不能指向 ~/.dsh：会污染正在使用的 desktop profile');
  process.exit(2);
}

const profileDir = path.join(home, 'profiles', profile);
if (!existsSync(profileDir)) {
  console.error(`FAIL  profile 不存在: ${profileDir}`);
  process.exit(2);
}

const results = [];
const expect = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
};

// ---------- 1. 把 runtimePath 写进 profile 的 patch 层 ----------
const patchPath = path.join(profileDir, 'cordis.patch.yml');
const backupPath = `${patchPath}.bak-local-e2e`;
if (existsSync(patchPath) && !existsSync(backupPath)) copyFileSync(patchPath, backupPath);
const yamlPath = String(runtimePath).replace(/\\/g, '/');
const patch = [
  '# 由 scripts/local-e2e.mjs 生成；原文件已备份为 cordis.patch.yml.bak-local-e2e',
  '- id: dsh-seekmemory',
  '  config:',
  `    runtimePath: '${yamlPath}'`,
  '    subjectMode: fixed',
  "    subjectKey: 'local:e2e:user'",
  '',
].join('\n');
writeFileSync(patchPath, patch, 'utf8');
console.log(`已写 patch: ${patchPath}`);
console.log(`   runtimePath = ${yamlPath}`);

// ---------- 2. 起 DSH（隔离 home，RUN_AS_NODE，不加载 Electron app 层） ----------
const cli = path.join(path.dirname(dshExe), 'resources', 'app.asar', 'dsh', 'node_modules', '@deepseek-ai', 'dsh', 'lib', 'bin.js');
const logPath = path.join(home, 'seekmemory-logs', 'seekmemory.log');
const before = existsSync(logPath) ? readFileSync(logPath, 'utf8').length : 0;

console.log(`\n起 DSH: profile=${profile}  home=${home}`);
console.log(`  task = ${task}`);
const t0 = Date.now();
const r = spawnSync(dshExe, [cli, '--profile', profile, task], {
  env: { ...process.env, ELECTRON_RUN_AS_NODE: '1', DSH_HOME: home },
  timeout: timeoutMs,
  encoding: 'utf8',
  windowsHide: true,
});
const elapsed = Math.round((Date.now() - t0) / 1000);
console.log(`DSH 退出: code=${r.status}  ${elapsed}s`);
if (r.error) console.log(`  spawn error: ${r.error.message}`);

// ---------- 3. 读插件日志（只取本次新增部分） ----------
const after = existsSync(logPath) ? readFileSync(logPath, 'utf8') : '';
const fresh = after.slice(before);
const lines = fresh.split(/\r?\n/).filter(Boolean);
console.log(`\n本次新增插件日志 ${lines.length} 行`);

const has = (needle) => fresh.includes(needle);
expect('插件 apply 执行了', has('apply 开始'));
expect('内核已连接（不是 not_configured）', has('已连接') && !has('未连接（not_configured）'),
  has('未连接（not_configured）') ? '日志里仍是 not_configured' : '');
expect('没有「捕获失败 reason=not_configured」', !has('捕获失败 reason=not_configured'));
expect('钩子注册完成', has('钩子注册完成'));
expect('卸载时钩子全部回收', has('钩子全部回收'));

// ---------- 4. 顺带跑两个契约级脚本 ----------
// 宿主刚退出时内核可能还在收尾上一条连接（单线程 HTTPServer），立刻发请求会被
// 阻塞到超时。等一小会儿再验，避免把时序问题误判成契约问题。
await new Promise((resolve) => setTimeout(resolve, 1500));
console.log('\n--- 内核端点契约 ---');
const contract = spawnSync(process.execPath, [path.join(HERE, 'check-kernel-contract.mjs'), '--runtime', runtimePath], {
  encoding: 'utf8',
  windowsHide: true,
  cwd: process.cwd(),
});
process.stdout.write(contract.stdout ?? '');
if (contract.status !== 0) {
  process.stderr.write(contract.stderr ?? '');
  expect('内核端点契约（含抽取提交）', false,
    contract.status === 2 ? '未完成：抽取计划/提交返回 501' : `exit=${contract.status}`);
} else expect('内核端点契约（含抽取提交）', true);

console.log('--- 适配器通路冒烟 ---');
const smoke = spawnSync(process.execPath, [path.join(HERE, 'smoke-contract.mjs'), '--runtime', runtimePath], {
  encoding: 'utf8',
  windowsHide: true,
  cwd: process.cwd(),
});
process.stdout.write(smoke.stdout ?? '');
if (smoke.status !== 0) {
  process.stderr.write(smoke.stderr ?? '');
  expect('适配器通路冒烟（11 项）', false,
    smoke.status === 2 ? '未完成：尚无已抽取记忆，不能验证召回/隐私/预算' : `exit=${smoke.status}`);
} else expect('适配器通路冒烟（11 项）', true);

// ---------- 5. 结论 ----------
const failed = results.filter((x) => !x.ok);
console.log(`\n================ 结论 ================`);
for (const x of results) console.log(`  ${x.ok ? '✔' : '✘'} ${x.name}`);
console.log(failed.length === 0
  ? '\n本地端到端：通。DSH 宿主 → 适配器 → 内核 全链路成立。'
  : `\n本地端到端：不通（${failed.length} 项失败）。\n  先看上面失败项：apply 失败=插件没加载；not_configured=适配器没连上内核；契约失败=内核没实现契约。`);
console.log(`\n回滚：patch 已备份在 ${backupPath}`);
process.exitCode = failed.length === 0 ? 0 : 1;
