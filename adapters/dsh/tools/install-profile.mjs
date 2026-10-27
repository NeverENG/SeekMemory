#!/usr/bin/env node
/**
 * 把 dsh-seekmemory 接进一个 DSH profile（默认 web）。
 *
 * 设计原则：
 *   - **幂等**：重复跑不会重复添加，也不会把 package.json 写乱
 *   - **先备份**：改之前把 package.json / cordis.patch.yml 复制到工作区
 *   - **可回滚**：同时生成 rollback-<profile>.cmd
 *   - **不碰 pnpm**：只用 link: + junction，避免 lockfile/网络/构建
 *
 * 用法：
 *   node tools/install-profile.mjs --profile web --plugin /path/to/dsh-seekmemory
 *   node tools/install-profile.mjs --profile web --uninstall
 *
 * --plugin 必填（安装时）：指向 dsh-seekmemory 包目录，没有内置默认值。
 * --backup-dir / --rollback-dir 可选：默认都落在系统临时目录，不写死任何本机路径。
 *
 * 退出码：0 成功；1 失败（失败时不会留下半截状态：package.json 原子写）
 */

import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync, symlinkSync, lstatSync, copyFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';

const argv = process.argv.slice(2);
function arg(name, fallback = '') {
  const i = argv.indexOf(name);
  return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
}
const has = (name) => argv.includes(name);

const profileName = arg('--profile', 'web');
const pluginArg = arg('--plugin', '');
const uninstall = has('--uninstall');
const PLUGIN = 'dsh-seekmemory';

if (!uninstall && !pluginArg) {
  fail('缺少 --plugin <plugin-dir>\n      node tools/install-profile.mjs --profile web --plugin /path/to/dsh-seekmemory');
}
const pluginDir = pluginArg ? path.resolve(pluginArg) : '';

const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const profileDir = path.join(DSH_HOME, 'profiles', profileName);
const pkgPath = path.join(profileDir, 'package.json');
const nmDir = path.join(profileDir, 'node_modules');
const linkPath = path.join(nmDir, PLUGIN);

function fail(msg) {
  console.error(`FAIL  ${msg}`);
  process.exitCode = 1;
  process.exit();
}

if (!existsSync(pkgPath)) fail(`找不到 profile: ${pkgPath}`);

const original = readFileSync(pkgPath, 'utf8');
let pkg;
try {
  pkg = JSON.parse(original);
} catch (err) {
  fail(`package.json 不是合法 JSON: ${err.message}`);
}

// ---------- 备份 ----------
const stamp = new Date().toISOString().replace(/[:.]/g, '-');
const backupRoot = arg('--backup-dir', path.join(os.tmpdir(), 'dsh-seekmemory-backup'));
const backupDir = path.join(backupRoot, `profile-${profileName}-${stamp}`);
if (!uninstall) {
  mkdirSync(backupDir, { recursive: true });
  copyFileSync(pkgPath, path.join(backupDir, 'package.json'));
  const patch = path.join(profileDir, 'cordis.patch.yml');
  if (existsSync(patch)) copyFileSync(patch, path.join(backupDir, 'cordis.patch.yml'));
  console.log(`备份: ${backupDir}`);
}

// ---------- 生成回滚脚本（纯 ASCII，双击可用） ----------
function writeRollback() {
  const lines = [
    '@echo off',
    'REM Rollback dsh-seekmemory from profile: ' + profileName,
    'REM Generated ' + stamp + ' - safe to double-click',
    'setlocal',
    'set PKG=' + pkgPath,
    uninstall ? '' : 'set BAK=' + path.join(backupDir, 'package.json'),
    uninstall ? '' : 'if exist "%BAK%" copy /Y "%BAK%" "%PKG%"',
    'if exist "' + linkPath + '" rmdir "' + linkPath + '"',
    'echo.',
    'echo Done. Restart DSH to apply.',
    'echo.',
    'pause',
  ].filter(Boolean);
  const rollbackDir = arg('--rollback-dir', os.tmpdir());
  mkdirSync(rollbackDir, { recursive: true });
  const file = path.join(rollbackDir, `rollback-${profileName}.cmd`);
  writeFileSync(file, lines.join('\r\n') + '\r\n', 'ascii');
  console.log(`回滚脚本: ${file}`);
}
writeRollback();

// ---------- 安装 / 卸载 ----------
pkg.dependencies = pkg.dependencies || {};
pkg.dsh = pkg.dsh || {};
pkg.dsh.profile = pkg.dsh.profile || {};
pkg.dsh.profile.bundles = Array.isArray(pkg.dsh.profile.bundles) ? pkg.dsh.profile.bundles : [];

if (uninstall) {
  delete pkg.dependencies[PLUGIN];
  pkg.dsh.profile.bundles = pkg.dsh.profile.bundles.filter((b) => b !== PLUGIN);
  if (existsSync(linkPath) || lstatSymbolic(linkPath)) {
    try {
      lstatSync(linkPath);
      // junction 用 rmdir 删（Node 的 unlink 对 junction 在 Windows 上也可用）
      unlinkDir(linkPath);
    } catch {
      /* 不存在就算了 */
    }
  }
  console.log('已移除依赖与 bundles 条目');
} else {
  if (!existsSync(pluginDir)) fail(`插件目录不存在: ${pluginDir}`);
  pkg.dependencies[PLUGIN] = `link:${pluginDir.replace(/\\/g, '/')}`;
  if (!pkg.dsh.profile.bundles.includes(PLUGIN)) pkg.dsh.profile.bundles.push(PLUGIN);

  // junction（不复制文件，源码改了立刻生效）
  mkdirSync(nmDir, { recursive: true });
  const exists = lstatSymbolic(linkPath);
  if (!exists) {
    symlinkSync(pluginDir, linkPath, 'junction');
    console.log(`junction: ${linkPath} -> ${pluginDir}`);
  } else {
    console.log(`junction 已存在（跳过）: ${linkPath}`);
  }
}

// ---------- 原子写回 ----------
const next = JSON.stringify(pkg, null, 2) + '\n';
if (next === original) {
  console.log('package.json 无变化');
} else {
  const tmp = `${pkgPath}.tmp-${process.pid}`;
  writeFileSync(tmp, next, 'utf8');
  renameSync(tmp, pkgPath);
  console.log('package.json 已更新（原子写）');
}

console.log('\n--- 结果 ---');
console.log('dependencies[PLUGIN] =', pkg.dependencies[PLUGIN] ?? '(none)');
console.log('bundles =', pkg.dsh.profile.bundles.join(', '));

function lstatSymbolic(p) {
  try {
    lstatSync(p);
    return true;
  } catch {
    return false;
  }
}
function unlinkDir(p) {
  // junction 用 rmdir 更稳：Node 的 rmSync 在 Windows 上会跟随 junction 删目标内容，
  // 绝不能误删插件源码目录。
  execFileSync('cmd', ['/c', 'rmdir', p]);
}
