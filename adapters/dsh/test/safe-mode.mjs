#!/usr/bin/env node
/**
 * 启动跳闸与开关测试。
 *
 * 验的是这些承诺：
 *   1. apply 走完立刻清 pending（pending 只覆盖启动阶段）
 *   2. 运行期未捕获异常 → crash.json → 下次启动跳闸
 *   3. 启动阶段单次遗留 + 曾成功过 → 判定强杀，**不**跳闸
 *   4. 启动阶段连续遗留 / 首次就没走完 → 跳闸
 *   5. 安全模式可自愈（连续 N 次启动后自动重试一次）
 *   6. 手动开关 DISABLE / FORCE 语义不变
 *   7. 日志真的落了盘，且**不含消息正文**
 */

import { mkdirSync, rmSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply } from '../src/index.js';
import { evaluateBoot, markCrash, readCrash, CRASH_FILE, STATE_FILE } from '../src/safe-mode.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'safemode');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

function fakeCtx({ throwOn = '' } = {}) {
  const handlers = new Map();
  const effects = [];
  const lines = [];
  const mk = (level) => (m) => lines.push(`${level}:${m}`);
  return {
    lines,
    handlers,
    effects,
    logger: { debug: mk('debug'), info: mk('info'), warn: mk('warn'), error: mk('error') },
    on(name, fn) {
      if (name === throwOn) throw new Error(`simulated failure on ${name}`);
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
      return () => handlers.set(name, (handlers.get(name) ?? []).filter((f) => f !== fn));
    },
    effect(fn) {
      effects.push(fn());
    },
    get() {
      return undefined;
    },
  };
}

function collector() {
  const lines = [];
  const mk = (level) => (m) => lines.push(`${level}:${m}`);
  return { lines, debug: mk('debug'), info: mk('info'), warn: mk('warn'), error: mk('error') };
}

function bootFile(dir) {
  return path.join(dir, STATE_FILE);
}
function crashFile(dir) {
  return path.join(dir, CRASH_FILE);
}
function logFile(dir) {
  return path.join(dir, 'seekmemory.log');
}
function readJson(p) {
  return JSON.parse(readFileSync(p, 'utf8'));
}
function writeBoot(dir, state) {
  mkdirSync(dir, { recursive: true });
  writeFileSync(bootFile(dir), JSON.stringify(state, null, 2));
}

function withEnv(patch, fn) {
  const saved = {};
  for (const [k, v] of Object.entries(patch)) {
    saved[k] = process.env[k];
    if (v === undefined) delete process.env[k];
    else process.env[k] = v;
  }
  try {
    return fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

const cfg = (dir) => ({ logDir: dir, stateDir: dir, subjectMode: 'fixed', subjectKey: 'k', recallTimeoutMs: 100 });

// ---------- 1. apply 走完：pending 立刻清掉 ----------
{
  const dir = path.join(TMP, 'fresh');
  mkdirSync(dir, { recursive: true });
  const ctx = fakeCtx();
  const state = withEnv({ DSH_HOME: dir }, () => {
    apply(ctx, cfg(dir));
    return readJson(bootFile(dir));
  });
  expect('apply 走完 → pending=false', state.pending, false);
  expect('apply 走完 → lastOkAt 已写入', typeof state.lastOkAt, 'string');
  expect('apply 走完 → 注册了 pre-step', (ctx.handlers.get('agent/pre-step') ?? []).length, 1);
}

// ---------- 2. 运行期崩溃信号：crash.json → 下次启动跳闸 ----------
{
  const dir = path.join(TMP, 'runtime-crash');
  mkdirSync(dir, { recursive: true });
  expect('markCrash 写盘成功', markCrash(dir, { message: 'boom', stack: 'at x' }), true);
  expect('crash.json 存在', existsSync(crashFile(dir)), true);
  const log = collector();
  const boot = evaluateBoot({ stateDir: dir, env: {}, logger: log });
  expect('读到 crash → mode=safe', boot.mode, 'safe');
  expect('读到 crash → reason=runtime-crash', boot.reason, 'runtime-crash');
  expect('跳闸后 crash.json 被清掉', existsSync(crashFile(dir)), false);
  expect('跳闸日志含未捕获异常', log.lines.some((l) => l.includes('未捕获异常')), true);
}

// ---------- 3. 端到端：apply → 运行期崩 → 再 apply 进安全模式 ----------
{
  const dir = path.join(TMP, 'e2e-crash');
  mkdirSync(dir, { recursive: true });
  withEnv({ DSH_HOME: dir }, () => apply(fakeCtx(), cfg(dir)));
  markCrash(dir, { message: 'simulated runtime crash' }); // 模拟 uncaughtExceptionMonitor
  const ctx2 = fakeCtx();
  withEnv({ DSH_HOME: dir }, () => apply(ctx2, cfg(dir)));
  expect('运行期崩过 → 下次启动一个钩子都不注册', (ctx2.handlers.get('agent/pre-step') ?? []).length, 0);
  expect('运行期崩过 → safeMode=true', readJson(bootFile(dir)).safeMode, true);
}

// ---------- 4. 启动阶段单次遗留 + 曾成功过 → 判强杀，不跳闸 ----------
{
  const dir = path.join(TMP, 'interrupted-once');
  writeBoot(dir, {
    pending: true,
    attempts: 1,
    lastStartAt: new Date().toISOString(),
    lastOkAt: new Date(Date.now() - 3600_000).toISOString(),
    safeMode: false,
  });
  const log = collector();
  const boot = evaluateBoot({ stateDir: dir, env: {}, logger: log });
  expect('单次遗留 + 曾成功 → mode=run', boot.mode, 'run');
  expect('单次遗留 + 曾成功 → reason=recovered-interrupted', boot.reason, 'recovered-interrupted');
  expect('豁免后 attempts 重置为 1', readJson(bootFile(dir)).attempts, 1);
  expect('豁免有说明日志', log.lines.some((l) => l.includes('强杀')), true);
}

// ---------- 5. 连续 3 次遗留 → 跳闸（即使曾成功过） ----------
{
  const dir = path.join(TMP, 'interrupted-thrice');
  writeBoot(dir, {
    pending: true,
    attempts: 3,
    lastStartAt: new Date().toISOString(),
    lastOkAt: new Date(Date.now() - 3600_000).toISOString(),
    safeMode: false,
  });
  const boot = evaluateBoot({ stateDir: dir, env: {}, logger: collector() });
  expect('连续 3 次遗留 → mode=safe', boot.mode, 'safe');
  expect('连续 3 次遗留 → reason=startup-did-not-complete', boot.reason, 'startup-did-not-complete');
}

// ---------- 6. 首次启动就没走完 → 直接跳闸 ----------
{
  const dir = path.join(TMP, 'first-crash');
  writeBoot(dir, { pending: true, attempts: 1, lastStartAt: new Date().toISOString(), lastOkAt: null, safeMode: false });
  const ctx = fakeCtx();
  withEnv({ DSH_HOME: dir }, () => apply(ctx, cfg(dir)));
  expect('首次启动就崩 → 不注册钩子', (ctx.handlers.get('agent/pre-step') ?? []).length, 0);
  expect('首次启动就崩 → safeMode=true', readJson(bootFile(dir)).safeMode, true);
}

// ---------- 7. 安全模式自愈：连续 3 次后自动重试 ----------
{
  const dir = path.join(TMP, 'auto-retry');
  writeBoot(dir, {
    pending: false,
    attempts: 0,
    safeMode: true,
    safeLaunches: 2,
    reason: 'startup-did-not-complete',
    safeSince: new Date().toISOString(),
  });
  const log = collector();
  const boot = evaluateBoot({ stateDir: dir, env: {}, logger: log });
  expect('安全模式第 3 次启动 → 自动重试', boot.mode, 'run');
  expect('自动重试 → reason=auto-retry', boot.reason, 'auto-retry');
  expect('自动重试后 safeMode=false', readJson(bootFile(dir)).safeMode, false);
  expect('自动重试有日志', log.lines.some((l) => l.includes('自动重试')), true);
}

// ---------- 8. 安全模式未到阈值 → 保持并计数 ----------
{
  const dir = path.join(TMP, 'auto-retry');
  writeBoot(dir, {
    pending: false,
    attempts: 0,
    safeMode: true,
    safeLaunches: 0,
    reason: 'startup-did-not-complete',
    safeSince: new Date().toISOString(),
  });
  const boot = evaluateBoot({ stateDir: dir, env: {}, logger: collector() });
  expect('未到阈值 → mode=safe', boot.mode, 'safe');
  expect('未到阈值 → 计数 +1', readJson(bootFile(dir)).safeLaunches, 1);
}

// ---------- 9. 手动开关：不注册、不写状态 ----------
{
  const dir = path.join(TMP, 'disabled');
  mkdirSync(dir, { recursive: true });
  const ctx = fakeCtx();
  withEnv({ DSH_HOME: dir, SEEKMEMORY_DISABLE: '1' }, () => apply(ctx, cfg(dir)));
  expect('DISABLE=1 → 无 pre-step', (ctx.handlers.get('agent/pre-step') ?? []).length, 0);
  expect('DISABLE=1 → 不写 boot.json', existsSync(bootFile(dir)), false);
  expect('DISABLE=1 → 有说明日志', ctx.lines.some((l) => l.includes('SEEKMEMORY_DISABLE')), true);
}

// ---------- 10. FORCE=1 解除（顺带清 crash） ----------
{
  const dir = path.join(TMP, 'crashed');
  writeBoot(dir, {
    pending: false,
    attempts: 0,
    safeMode: true,
    safeLaunches: 2,
    reason: 'runtime-crash',
    safeSince: new Date().toISOString(),
  });
  markCrash(dir, { message: 'leftover' });
  const ctx = fakeCtx();
  const state = withEnv({ DSH_HOME: dir, SEEKMEMORY_FORCE: '1' }, () => {
    apply(ctx, cfg(dir));
    return readJson(bootFile(dir));
  });
  expect('FORCE=1 → 恢复注册钩子', (ctx.handlers.get('agent/pre-step') ?? []).length, 1);
  expect('FORCE=1 → safeMode=false', state.safeMode, false);
  expect('FORCE=1 → 清掉遗留 crash.json', existsSync(crashFile(dir)), false);
}

// ---------- 11. 钩子注册失败 → 不清 pending，下次跳闸 ----------
{
  const dir = path.join(TMP, 'hookfail');
  mkdirSync(dir, { recursive: true });
  const ctx = fakeCtx({ throwOn: 'agent/pre-step' });
  const state = withEnv({ DSH_HOME: dir }, () => {
    apply(ctx, cfg(dir));
    return readJson(bootFile(dir));
  });
  expect('注册失败 → 保持 pending=true', state.pending, true);
  const ctx2 = fakeCtx();
  withEnv({ DSH_HOME: dir }, () => apply(ctx2, cfg(dir)));
  expect('注册失败后再启动 → 安全模式', readJson(bootFile(dir)).safeMode, true);
}

// ---------- 12. 日志落了盘，且含里程碑 ----------
{
  const dir = path.join(TMP, 'fresh');
  const log = readFileSync(logFile(dir), 'utf8');
  expect('日志文件存在且非空', log.length > 100, true);
  expect('日志含 apply 开始', log.includes('apply 开始'), true);
  expect('日志含跳闸结果', log.includes('跳闸结果'), true);
  expect('日志含"已就绪"', log.includes('已就绪'), true);
  expect('日志含启动阶段完成标记', log.includes('启动阶段完成标记'), true);
}

// ---------- 13. 日志不含消息正文 ----------
{
  const dir = path.join(TMP, 'privacy');
  mkdirSync(dir, { recursive: true });
  const ctx = fakeCtx();
  const SECRET = '机密内容_不该进日志_9f3a';
  withEnv({ DSH_HOME: dir }, () => {
    apply(ctx, cfg(dir));
    const onEvent = ctx.handlers.get('session/event')?.[0];
    onEvent?.({ id: 's1' }, { type: 'user/message', time: Date.now(), data: { id: 'm1', content: [{ type: 'text', text: SECRET }] } });
  });
  const log = readFileSync(logFile(dir), 'utf8');
  expect('日志里没有消息正文', log.includes(SECRET), false);
}

// ---------- 14. crash 读取接口 ----------
{
  const dir = path.join(TMP, 'crash-read');
  mkdirSync(dir, { recursive: true });
  expect('无 crash 时读到 null', readCrash(dir), null);
  markCrash(dir, { message: 'x'.repeat(800) });
  const c = readCrash(dir);
  expect('crash 消息被截断到 500', c.message.length, 500);
  expect('crash 带时间戳', typeof c.at, 'string');
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
