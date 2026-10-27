#!/usr/bin/env node
/**
 * 跨平台安装后自检（postinstall-check.cmd 的 node 等价实现）。
 *
 * 为什么需要它：若 package.json 缺 `dsh.bundle.patch`，profile 会在组装阶段
 * **静默跳过**整包——宿主不报错、插件凭空消失，只有 dump-config 能看见。
 *
 * 两种用法：
 *   1) 自己调 dsh 生成 dump 再校验：
 *        node scripts/postinstall-check.mjs --dsh-exe "/path/to/DeepSeek Harness" [--profile web] [--home <dir>]
 *        node scripts/postinstall-check.mjs --dsh-cli /path/to/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js
 *   2) 只校验已有的 dump（不需要 DSH）：
 *        node scripts/postinstall-check.mjs --dump <dump.yml>
 *
 * 子进程的 stdout/stderr 直接写文件描述符而不是管道：Windows 受限沙箱下
 * 管道 stdio 会 EPERM，这条写法在本地和 CI 都能跑。
 *
 * 退出码：0 已组装；1 被跳过/缺失；2 参数或执行错误。
 */

import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, openSync, closeSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

/**
 * 校验 dump 文本里是否真的组装了目标插件。
 * @param {string} text dump-config 的输出
 * @param {string} expect 插件包名
 * @returns {{ok:boolean, reason:'assembled'|'skipped'|'missing', detail:string}}
 */
export function verifyDump(text, expect = 'dsh-seekmemory') {
  const esc = expect.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const entryRe = new RegExp(`-\\s*id:\\s*['"]?${esc}['"]?\\s*$`, 'm');
  const skipRe = new RegExp(`skipping profile bundle\\s+["']?${esc}`, 'i');
  const present = entryRe.test(text);
  const skipped = skipRe.test(text);
  if (present && !skipped) {
    return { ok: true, reason: 'assembled', detail: `${text.split('\n').length} lines` };
  }
  if (skipped) {
    const line = text.split('\n').find((l) => skipRe.test(l)) ?? '';
    return { ok: false, reason: 'skipped', detail: line.trim().slice(0, 200) };
  }
  return { ok: false, reason: 'missing', detail: 'id not found in composed tree' };
}

function cli() {
  const argv = process.argv.slice(2);
  const arg = (name, fallback = '') => {
    const i = argv.indexOf(name);
    return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
  };
  const profile = arg('--profile', 'web');
  const expect = arg('--expect', 'dsh-seekmemory');
  const explicitDump = arg('--dump');
  const home = arg('--home', path.join(os.tmpdir(), 'dsh-seekmemory-check-home'));
  const dshExe = arg('--dsh-exe');
  const dshCli = arg('--dsh-cli');
  const keep = argv.includes('--keep');

  let dumpPath = explicitDump;
  let generated = false;
  let errPath = '';

  if (!dumpPath) {
    if (!dshExe && !dshCli) {
      console.error('用法: node scripts/postinstall-check.mjs --dsh-exe <DSH exe> | --dsh-cli <bin.js>');
      console.error('      [--profile web] [--home <dir>] [--expect <plugin>] [--keep]');
      console.error('   或: node scripts/postinstall-check.mjs --dump <existing-dump.yml>');
      process.exit(2);
    }

    mkdirSync(home, { recursive: true });
    dumpPath = path.join(home, 'postinstall-dump.yml');
    errPath = path.join(home, 'postinstall-dump.err');

    const outFd = openSync(dumpPath, 'w');
    const errFd = openSync(errPath, 'w');
    const env = { ...process.env, DSH_HOME: home };

    let exe = process.execPath;
    let args;
    if (dshCli && !dshExe) {
      args = [dshCli, '--dump-config', '--profile', profile];
    } else {
      const cliFile =
        dshCli ||
        path.join(
          path.dirname(dshExe),
          'resources',
          'app.asar',
          'dsh',
          'node_modules',
          '@deepseek-ai',
          'dsh',
          'lib',
          'bin.js',
        );
      exe = dshExe;
      args = [cliFile, '--dump-config', '--profile', profile];
      env.ELECTRON_RUN_AS_NODE = '1';
    }

    const r = spawnSync(exe, args, { stdio: ['ignore', outFd, errFd], env });
    closeSync(outFd);
    closeSync(errFd);
    generated = true;

    if (r.error || r.status !== 0) {
      console.error(`FAIL  dump-config 失败: ${r.error?.message ?? `exit ${r.status}`}`);
      try {
        console.error(readFileSync(errPath, 'utf8').slice(0, 2000));
      } catch {
        /* 没有 stderr 可读就算了 */
      }
      process.exit(2);
    }
  }

  if (!existsSync(dumpPath)) {
    console.error(`FAIL  dump 文件不存在: ${dumpPath}`);
    process.exit(2);
  }

  const res = verifyDump(readFileSync(dumpPath, 'utf8'), expect);
  if (res.ok) {
    console.log(`PASS  已组装: ${expect}  (${res.detail})`);
  } else if (res.reason === 'skipped') {
    console.error(`FAIL  被静默跳过: ${expect}`);
    console.error(`      ${res.detail}`);
    console.error('      常见原因: package.json 缺 dsh.bundle.patch，或 node_modules 里没有该包');
  } else {
    console.error(`FAIL  组装树里找不到: ${expect}`);
    console.error('      检查 profile 的 dsh.profile.bundles 是否含有该包名');
  }

  if (generated) {
    if (keep) {
      console.log(`      dump: ${dumpPath}`);
    } else {
      for (const f of [dumpPath, errPath]) {
        try {
          rmSync(f, { force: true });
        } catch {
          /* 清理失败不影响结论 */
        }
      }
    }
  }

  process.exit(res.ok ? 0 : 1);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) cli();
