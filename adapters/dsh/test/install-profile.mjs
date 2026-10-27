#!/usr/bin/env node
/**
 * install-profile.mjs 的 junction 状态用例。
 *
 * 这件事曾经静默出错：安装器只看"node_modules 下有没有这个条目"，
 * 不校验它指向哪里。换个目录重装时，package.json 写成新路径、
 * junction 却仍指旧目录，导致"配置说 A、实物是 B"。
 *
 * 四个场景：
 *   A 全新安装        → 建 junction
 *   B 重复安装同一目录 → 识别为已指向，不重建
 *   C 换目录重装      → 重新指向，且**原目标目录内容必须完好**
 *   D 实体目录占位    → 明确失败，且不删除实体目录
 *
 * 两点环境事实（本机实测，见 PR 描述）：
 *   1. Node 在此环境把 junction 当普通目录：isSymbolicLink=false、readlink=EINVAL、
 *      realpath 不解析。所以"指向是否一致"只能用 stat 解析后的 (dev, ino) 比较。
 *   2. 子进程 stdio 用文件描述符而不是管道：受限沙箱里管道会 EPERM。
 */

import { spawnSync } from 'node:child_process';
import {
  mkdirSync,
  writeFileSync,
  rmSync,
  statSync,
  lstatSync,
  rmdirSync,
  unlinkSync,
  readFileSync,
  openSync,
  closeSync,
} from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const SCRIPT = path.join(ROOT, 'tools', 'install-profile.mjs');
const TMP = path.join(ROOT, '.tmp', 'install-profile');
const LOG = path.join(TMP, 'out.log');

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

/** junction 是否解析到同一个目录（用 dev+ino，不用 readlink） */
function sameTarget(link, dir) {
  try {
    const a = statSync(link);
    const b = statSync(dir);
    return a.dev === b.dev && a.ino === b.ino;
  } catch {
    return false;
  }
}

/** 删链接本身：POSIX 用 unlink，Windows 的 junction 用 rmdir */
function removeLink(p) {
  try {
    unlinkSync(p);
  } catch {
    try {
      rmdirSync(p);
    } catch {
      /* 已不存在 */
    }
  }
}

function setup() {
  rmSync(TMP, { recursive: true, force: true });
  const home = path.join(TMP, 'home');
  const profile = path.join(home, 'profiles', 'web');
  mkdirSync(profile, { recursive: true });
  writeFileSync(
    path.join(profile, 'package.json'),
    JSON.stringify({ name: 'profile-under-test', dependencies: {}, dsh: { profile: { bundles: [] } } }, null, 2) + '\n',
    'utf8',
  );
  const a = path.join(TMP, 'pluginA');
  const b = path.join(TMP, 'pluginB');
  for (const d of [a, b]) {
    mkdirSync(d, { recursive: true });
    writeFileSync(path.join(d, 'index.js'), 'export default {}\n', 'utf8');
  }
  return { home, profile, a, b, link: path.join(profile, 'node_modules', 'dsh-seekmemory') };
}

function run(env, pluginDir) {
  const fd = openSync(LOG, 'w');
  const r = spawnSync(process.execPath, [SCRIPT, '--profile', 'web', '--plugin', pluginDir], {
    stdio: ['ignore', fd, fd],
    env: { ...process.env, DSH_HOME: env.home },
  });
  closeSync(fd);
  return { status: r.status, error: r.error, out: readFileSync(LOG, 'utf8') };
}

const env = setup();

// 探测：与用例相同的 stdio 方式
const pfd = openSync(path.join(TMP, 'probe.log'), 'w');
const probe = spawnSync(process.execPath, ['-e', 'process.exit(0)'], { stdio: ['ignore', pfd, pfd] });
closeSync(pfd);

if (probe.error) {
  console.log(`SKIP  当前环境子进程不可用（${probe.error.code || probe.error.message}），CI 上会真跑`);
  process.exitCode = 0;
} else {
  // A. 全新安装
  {
    const r = run(env, env.a);
    expect('A 全新安装 → exit 0', r.status, 0);
    expect('A junction 解析到 pluginA', sameTarget(env.link, env.a), true);
  }

  // B. 重复安装同一目录
  {
    const r = run(env, env.a);
    expect('B 重复安装 → exit 0', r.status, 0);
    expect('B 识别为已指向（不重建）', r.out.includes('已指向目标'), true);
  }

  // C. 换目录重装：必须重新指向，且旧目标内容完好
  {
    const r = run(env, env.b);
    expect('C 换目录 → exit 0', r.status, 0);
    expect('C 提示已移除旧链接', r.out.includes('已移除旧链接'), true);
    expect('C junction 解析到 pluginB', sameTarget(env.link, env.b), true);
    expect('C 旧目标 pluginA 仍在', lstatSync(path.join(env.a, 'index.js')).isFile(), true);
  }

  // D. 实体非空目录占位：必须明确失败，且不删除用户内容
  {
    removeLink(env.link);
    mkdirSync(env.link, { recursive: true });
    writeFileSync(path.join(env.link, 'marker.txt'), 'keep me\n', 'utf8');
    const r = run(env, env.a);
    expect('D 实体非空目录 → exit 1', r.status, 1);
    expect('D 报错可读', r.out.includes('无法自动替换'), true);
    expect('D 实体目录未被删除', lstatSync(path.join(env.link, 'marker.txt')).isFile(), true);
  }

  // 清理：只删链接/目录本身，然后删临时根
  removeLink(env.link);
  try {
    rmSync(env.link, { recursive: true, force: true });
  } catch {
    /* 已不存在 */
  }
  rmSync(TMP, { recursive: true, force: true });

  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
  process.exitCode = failed === 0 ? 0 : 1;
}
