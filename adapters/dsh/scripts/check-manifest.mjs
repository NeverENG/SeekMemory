#!/usr/bin/env node
/**
 * G13 / G4 静态检查：交付前必跑，进 CI。
 *
 * 检查的都是"会静默出事"的东西：
 *   1. engines.dsh 必须存在且**没有上界**（有上界 = 宿主一发新版就判 risk）
 *   2. 所有 @deepseek-ai/dsh* peer 必须标 optional（不标 = 失配即 risk）
 *   3. src/ 里**不允许静态值导入** @deepseek-ai/*（符号被删会让整棵插件树崩）
 *   4. src/ 里不允许出现 nullable（DSH value schema 白名单外，编译期抛）
 *   5. package.json 与 dsh.plugin.json 的 version / engines.dsh 必须一致
 *   6. dsh.plugin.json 的 components.host 文件必须存在
 *
 * 退出码：0 全过；1 有失败。**不要用输出计数判断成败**（PS 管道会造假）。
 */

import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const results = [];

function check(name, fn) {
  try {
    const detail = fn();
    results.push({ ok: true, name, detail: detail ?? '' });
  } catch (err) {
    results.push({ ok: false, name, detail: err?.message ?? String(err) });
  }
}

function readJson(rel) {
  return JSON.parse(readFileSync(path.join(ROOT, rel), 'utf8'));
}

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.(js|mjs|cjs|ts)$/.test(entry)) out.push(full);
  }
  return out;
}

const pkg = readJson('package.json');
const manifest = readJson('dsh.plugin.json');

// 1. engines.dsh 无上界
check('engines.dsh 存在且无上界', () => {
  const range = pkg.engines?.dsh ?? '';
  if (!range) throw new Error('package.json 缺 engines.dsh');
  if (range.includes('<')) throw new Error(`含上界 "${range}"：宿主一发新版就会被判 risk，改成 ">=x.y.z"`);
  if (!range.startsWith('>=')) throw new Error(`未用下限形式："${range}"`);
  return range;
});

// 2. dsh* peer 必须 optional
check('所有 @deepseek-ai/dsh* peer 标 optional', () => {
  const peers = Object.keys(pkg.peerDependencies ?? {}).filter((n) => /^@deepseek-ai\/dsh/.test(n));
  const bad = peers.filter((n) => pkg.peerDependenciesMeta?.[n]?.optional !== true);
  if (bad.length) throw new Error(`未标 optional: ${bad.join(', ')}`);
  return peers.length ? `${peers.length} 个` : '无';
});

// 3. 无静态值导入
check('src/ 无静态值导入 @deepseek-ai/*', () => {
  const bad = [];
  for (const file of walk(path.join(ROOT, 'src'))) {
    const text = readFileSync(file, 'utf8');
    const re = /^\s*import\s+(?:type\s+)?[^;]*?from\s+['"]@deepseek-ai\/[^'"]+['"]/gm;
    for (const m of text.matchAll(re)) {
      const stmt = m[0];
      if (/^\s*import\s+type\s/.test(stmt)) continue; // 纯类型导入会被擦除，安全
      if (/^\s*import\s+['"]/.test(stmt)) continue; // 副作用导入，单独评估
      bad.push(`${path.relative(ROOT, file)}: ${stmt.trim().slice(0, 60)}`);
    }
  }
  if (bad.length) throw new Error(`发现 ${bad.length} 处：\n    ${bad.join('\n    ')}`);
  return '仅动态 import';
});

// 4. 无 nullable
check('src/ 无 nullable', () => {
  const hits = [];
  for (const file of walk(path.join(ROOT, 'src'))) {
    const text = readFileSync(file, 'utf8');
    if (/\bnullable\b/.test(text)) hits.push(path.relative(ROOT, file));
  }
  if (hits.length) throw new Error(`命中：${hits.join(', ')}（DSH value schema 白名单外，编译期抛）`);
  return '无';
});

// 5. 版本字段一致
check('package.json 与 dsh.plugin.json 一致', () => {
  if (pkg.version !== manifest.version) throw new Error(`version 不一致 ${pkg.version} vs ${manifest.version}`);
  const a = pkg.engines?.dsh ?? '';
  const b = manifest.engines?.dsh ?? '';
  if (a !== b) throw new Error(`engines.dsh 不一致 "${a}" vs "${b}"`);
  return `v${pkg.version} / ${a}`;
});

// 6. components.host 存在
check('components.host 指向真实文件', () => {
  const host = manifest.components?.host;
  if (!host) throw new Error('dsh.plugin.json 缺 components.host');
  if (!existsSync(path.join(ROOT, host))) throw new Error(`文件不存在: ${host}`);
  return host;
});

// 7. bundle patch 必须声明且存在
// 没有它，profile 会在组装阶段**静默跳过**整个包（真机实测踩过：
// "profile bundle ... declares no dsh.bundle in its package.json"）——宿主不报错、
// 插件凭空消失，只有 dump-config 能看出来。
check('dsh.bundle.patch 声明且文件存在', () => {
  const patch = pkg.dsh?.bundle?.patch;
  if (!patch) throw new Error('package.json 缺 dsh.bundle.patch（会导致插件被静默跳过）');
  const full = path.join(ROOT, patch);
  if (!existsSync(full)) throw new Error(`patch 文件不存在: ${patch}`);
  const body = readFileSync(full, 'utf8');
  if (!/name:\s*['"]?dsh-seekmemory/m.test(body)) throw new Error(`patch 里没有挂载自身条目: ${patch}`);
  return patch;
});

// ---------- 输出 ----------
let failed = 0;
for (const r of results) {
  if (!r.ok) failed += 1;
  console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.detail ? `  — ${r.detail}` : ''}`);
}
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
