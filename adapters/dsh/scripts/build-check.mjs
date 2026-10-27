#!/usr/bin/env node
/**
 * 打包白名单自检（不依赖 npm）。
 *
 * 这个包没有构建步骤（纯 ESM），所以"build"在这里的含义是：
 * 确认 `files` 白名单与入口声明能真的打出一个可安装的包——
 * 少一个 dsh.plugin.json 就是装上去静默消失，属于发布级事故。
 *
 * 校验项：
 *   1. files 白名单里每一项都存在；
 *   2. 必需文件都在：dsh.plugin.json、cordis.patch.yml、README.md、src/index.js；
 *   3. 必需文件都在白名单内（否则打不进包）；
 *   4. main 与 exports 指向的文件存在。
 *
 * 退出码：0 通过；1 有问题。
 */

import { readFileSync, existsSync, statSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const pkg = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8'));

const problems = [];
const files = [];

function walk(rel) {
  const abs = path.join(ROOT, rel);
  if (!existsSync(abs)) {
    problems.push(`files 条目不存在: ${rel}`);
    return;
  }
  const st = statSync(abs);
  if (st.isDirectory()) {
    for (const name of readdirSync(abs).sort()) walk(path.posix.join(rel, name));
  } else {
    files.push({ rel: rel.replace(/\\/g, '/'), size: st.size });
  }
}

for (const entry of pkg.files ?? []) walk(entry);

// package.json 由 npm 自动纳入，不要求在 files 里
const REQUIRED = ['package.json', 'dsh.plugin.json', 'cordis.patch.yml', 'README.md', 'src/index.js'];
for (const must of REQUIRED) {
  if (!existsSync(path.join(ROOT, must))) problems.push(`缺少必需文件: ${must}`);
  if (must !== 'package.json' && !files.some((f) => f.rel === must)) {
    problems.push(`必需文件不在 files 白名单里: ${must}`);
  }
}

const targets = [pkg.main, ...Object.values(pkg.exports ?? {}).filter((v) => typeof v === 'string')];
for (const t of targets) {
  if (!t) continue;
  const rel = t.replace(/^\.\//, '');
  if (!existsSync(path.join(ROOT, rel))) problems.push(`main/exports 指向不存在: ${t}`);
}

// dsh 插件声明必须指向真实文件，否则宿主会静默跳过整包
const patch = pkg?.dsh?.bundle?.patch;
if (!patch) {
  problems.push('package.json 缺 dsh.bundle.patch');
} else {
  const rel = patch.replace(/^\.\//, '');
  if (!existsSync(path.join(ROOT, rel))) problems.push(`dsh.bundle.patch 指向不存在: ${patch}`);
  if (!files.some((f) => f.rel === rel)) problems.push(`dsh.bundle.patch 不在 files 白名单里: ${patch}`);
}

const total = files.reduce((s, f) => s + f.size, 0);
console.log(`packable files: ${files.length}, total ${(total / 1024).toFixed(1)} KB`);
for (const f of files.sort((a, b) => a.rel.localeCompare(b.rel))) {
  console.log(`  ${f.rel}  ${f.size}b`);
}

if (problems.length) {
  console.error('\nFAIL');
  for (const p of problems) console.error('  - ' + p);
  process.exitCode = 1;
} else {
  console.log('\nPASS  files 白名单、入口与 dsh.bundle.patch 一致');
}
