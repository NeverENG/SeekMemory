#!/usr/bin/env node
/**
 * postinstall-check 的用例：
 *   - 直接校验 verifyDump 的三种判定（已组装 / 静默跳过 / 找不到）
 *   - 子进程路径：用一个假 dsh 生成 dump，验证 --dsh-cli 分支真的能跑通
 *
 * 子进程用例在受限沙箱里会 EPERM（spawn 被拒），那种环境下打 SKIP 而不是 FAIL；
 * CI 上没有这个限制，会真的跑。
 */

import { spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyDump } from '../scripts/postinstall-check.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'postinstall');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}
function skip(name, why) {
  results.push({ ok: true, name, skipped: true });
  console.log(`SKIP  ${name}  — ${why}`);
}

const DUMP_OK = [
  'profiles:',
  '  web:',
  '    bundles:',
  '      - id: dsh-prime-memory',
  '        name: dsh-prime-memory',
  '      - id: dsh-seekmemory',
  '        name: dsh-seekmemory',
  '',
].join('\n');

const DUMP_MISSING = ['profiles:', '  web:', '    bundles:', '      - id: dsh-prime-memory', ''].join('\n');

const DUMP_SKIPPED = [
  'profiles:',
  '  web:',
  '    bundles:',
  '      - id: dsh-prime-memory',
  'warning: skipping profile bundle "dsh-seekmemory": missing dsh.bundle.patch',
  '',
].join('\n');

// 1. 已组装
{
  const r = verifyDump(DUMP_OK, 'dsh-seekmemory');
  expect('组装树含条目 → ok', [r.ok, r.reason], [true, 'assembled']);
}

// 2. 找不到
{
  const r = verifyDump(DUMP_MISSING, 'dsh-seekmemory');
  expect('组装树无条目 → missing', [r.ok, r.reason], [false, 'missing']);
}

// 3. 被静默跳过（宿主只 warning，不报错）
{
  const r = verifyDump(DUMP_SKIPPED, 'dsh-seekmemory');
  expect('出现 skipping 警告 → skipped', [r.ok, r.reason], [false, 'skipped']);
  expect('跳过原因可读', r.detail.includes('skipping profile bundle'), true);
}

// 4. 子进程路径：假 dsh 输出 dump
const fakeDsh = path.join(TMP, 'fake-dsh.mjs');
writeFileSync(
  fakeDsh,
  [
    '// 假 dsh：接受 --dump-config --profile，输出一段可控的组装树。',
    "const mode = process.env.FAKE_DUMP_MODE || 'ok';",
    "if (mode === 'fail') { console.error('boom'); process.exit(3); }",
    "const line = mode === 'missing' ? '' : '      - id: dsh-seekmemory\\n        name: dsh-seekmemory\\n';",
    "process.stdout.write('profiles:\\n  web:\\n    bundles:\\n' + line);",
    '',
  ].join('\n'),
  'utf8',
);

// 探测的是"管道 stdio 是否被允许"——受限沙箱只拒管道，不拒 'ignore'。
const spawnUsable = !spawnSync(process.execPath, ['-e', 'process.exit(0)'], { encoding: 'utf8' }).error;
if (!spawnUsable) {
  skip('子进程路径（--dsh-cli）', '当前环境 spawn 被拒（EPERM），CI 上会真跑');
} else {
  const script = path.join(ROOT, 'scripts', 'postinstall-check.mjs');
  const home = path.join(TMP, 'home');

  // 4a. 正常：假 dsh 输出含条目 → 0
  {
    const r = spawnSync(process.execPath, [script, '--dsh-cli', fakeDsh, '--home', home], { encoding: 'utf8' });
    expect('假 dsh 组装成功 → exit 0', r.status, 0);
  }

  // 4b. 缺条目 → 1
  {
    const r = spawnSync(process.execPath, [script, '--dsh-cli', fakeDsh, '--home', home], {
      encoding: 'utf8',
      env: { ...process.env, FAKE_DUMP_MODE: 'missing' },
    });
    expect('假 dsh 缺条目 → exit 1', r.status, 1);
  }

  // 4c. dsh 自身失败 → 2
  {
    const r = spawnSync(process.execPath, [script, '--dsh-cli', fakeDsh, '--home', home], {
      encoding: 'utf8',
      env: { ...process.env, FAKE_DUMP_MODE: 'fail' },
    });
    expect('假 dsh 执行失败 → exit 2', r.status, 2);
  }
}

const failed = results.filter((r) => !r.ok).length;
const skipped = results.filter((r) => r.skipped).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks${skipped ? `, ${skipped} skipped` : ''})`);
process.exitCode = failed === 0 ? 0 : 1;
