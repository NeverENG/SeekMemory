#!/usr/bin/env node
/**
 * 安装后自检：确认插件真的被组装进 profile。
 *
 * 为什么需要它：若 package.json 缺 `dsh.bundle.patch`，profile 会在组装阶段
 * **静默跳过**整包——宿主不报错、插件凭空消失，只有 dump-config 能看见。
 * 静态检查（check-manifest）能防我们自己的包，这个脚本防的是"装到某个 profile 后"。
 *
 * 用法（推荐由 postinstall-check.cmd 调用，避开沙箱 spawn 限制）：
 *   node scripts/check-installed.mjs --dump <dump.yml> [--expect dsh-seekmemory]
 *
 * 退出码：0 = 已组装；1 = 被跳过/缺失；2 = 参数或文件错误。
 */

import { readFileSync, existsSync } from 'node:fs';

const argv = process.argv.slice(2);
function arg(name, fallback = '') {
  const i = argv.indexOf(name);
  return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
}

const dump = arg('--dump');
const expect = arg('--expect', 'dsh-seekmemory');

if (!dump) {
  console.error('用法: node scripts/check-installed.mjs --dump <dump.yml> [--expect <plugin-name>]');
  process.exitCode = 2;
  process.exit();
}
if (!existsSync(dump)) {
  console.error(`FAIL  dump 文件不存在: ${dump}`);
  process.exitCode = 2;
  process.exit();
}

const text = readFileSync(dump, 'utf8');

// 组装树里应当出现：- id: <name>\n  name: <name>
const entryRe = new RegExp(`-\\s*id:\\s*['"]?${expect.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['"]?\\s*$`, 'm');
const present = entryRe.test(text);

// 被跳过的证据（宿主只给 warning，不失败）
const skipRe = new RegExp(`skipping profile bundle\\s+["']?${expect.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'i');
const skipped = skipRe.test(text);

if (present && !skipped) {
  console.log(`PASS  已组装: ${expect}`);
  console.log(`      dump: ${dump} (${text.split('\n').length} 行)`);
  process.exitCode = 0;
} else if (skipped) {
  console.error(`FAIL  被静默跳过: ${expect}`);
  const line = text.split('\n').find((l) => skipRe.test(l)) ?? '';
  console.error(`      ${line.trim().slice(0, 200)}`);
  console.error('      常见原因: package.json 缺 dsh.bundle.patch，或 node_modules 里没有该包');
  process.exitCode = 1;
} else {
  console.error(`FAIL  组装树里找不到: ${expect}`);
  console.error('      检查 profile 的 dsh.profile.bundles 是否含有该包名');
  process.exitCode = 1;
}
