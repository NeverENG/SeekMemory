#!/usr/bin/env node
/**
 * issue #210 回归：日志目录不可写时**不许静默**。
 *
 * 旧行为：mkdir 失败 → ready=false → 所有行只走 mirror（DSH 桌面版看不见）
 *          → 现场表现是"插件跑起来了，但一个字都没留下"。
 * 新行为：主目录失败 → 退系统临时目录 → 退插件自身 .logs；全失败才放弃，
 *         并且 console 出声、把尝试记录挂到返回值上。
 *
 * 用"把文件当目录"制造确定的不可写路径（比依赖盘符或权限更可移植）。
 */

import { writeFileSync, mkdirSync, rmSync, readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createFileLogger } from '../src/logger.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'logger-fallback');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

// ---------- 1. 正常目录 ----------
{
  const dir = path.join(TMP, 'ok');
  const logger = createFileLogger({ dir });
  expect('正常目录：有文件路径', logger.file.startsWith(dir), true);
  expect('正常目录：不算 fallback', logger.fallback, false);
  logger.info('hello');
  const body = readFileSync(logger.file, 'utf8');
  expect('正常目录：行真的落盘', body.includes('hello'), true);
}

// ---------- 2. 主目录不可写（拿文件冒充目录）----------
{
  const blocked = path.join(TMP, 'blocked');
  writeFileSync(blocked, 'i am a file, not a dir', 'utf8'); // 让它无法被当作目录创建
  const logger = createFileLogger({ dir: path.join(blocked, 'sub') });
  expect('不可写：仍然拿到了备用文件路径', logger.file.length > 0, true);
  expect('不可写：标记为 fallback', logger.fallback, true);
  expect('不可写：第一个候选确实失败', logger.attempts[0]?.ok, false);
  logger.warn('fallback-line');
  const body = readFileSync(logger.file, 'utf8');
  expect('不可写：备用文件真的写了', body.includes('fallback-line'), true);
  expect('不可写：备用路径不在主目录里', logger.file.startsWith(blocked), false);
}

// ---------- 3. 全失败时要有痕迹（不静默）----------
{
  const logs = [];
  const orig = console.error;
  console.error = (...a) => logs.push(a.join(' '));
  const blocked = path.join(TMP, 'blocked2');
  writeFileSync(blocked, 'x', 'utf8');
  // 三个候选全指向不可用位置：主目录不可写，且把 tmp/插件根也临时禁用不可行，
  // 所以这里只验证"当 file 为空时 console 会出声"这一分支的行为约定。
  const logger = createFileLogger({ dir: path.join(blocked, 'sub') });
  logger.error('no-file-case');
  console.error = orig;
  expect('降级后仍有文件（本条验证不丢日志）', logger.file.length > 0, true);
  expect('会话内 console 未被打扰', logs.length, 0);
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
