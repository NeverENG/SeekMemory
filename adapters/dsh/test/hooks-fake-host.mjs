#!/usr/bin/env node
/**
 * 假宿主测试：不需要真 DSH 就能验 M3/M4 的三条硬要求。
 *
 *   1. apply() 遇到任何配置都不抛（G13：抛了整棵插件树崩）
 *   2. pre-step 在内核可用时真的把记忆插进去，且消息形状可辨
 *   3. 内核不可用时 decision 原样返回（fail-open，不阻断对话）
 *   4. 卸载后钩子全部回收（不残留、不重复注册）
 *
 * 用进程内 HTTP 服务当内核；createUserMessage 走动态导入失败 → 兜底路径，
 * 顺带把兜底分支也测了。
 */

import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply } from '../src/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'fakehost');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

// ---------- 假宿主 ----------
function fakeCtx() {
  const handlers = new Map();
  const effects = [];
  const logLines = [];
  const mk = (level) => (m) => logLines.push(`${level}:${m}`);
  return {
    logLines,
    effects,
    handlers,
    logger: { debug: mk('debug'), info: mk('info'), warn: mk('warn'), error: mk('error') },
    on(name, fn) {
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
      return () => {
        const arr = handlers.get(name) ?? [];
        const i = arr.indexOf(fn);
        if (i >= 0) arr.splice(i, 1);
      };
    },
    effect(fn) {
      const dispose = fn();
      effects.push(dispose);
      return () => {};
    },
    get() {
      return undefined; // 没有已存在的 agent
    },
  };
}

// ---------- 内核 ----------
function serve({ block }) {
  return new Promise((resolve) => {
    const hits = { capture: 0, recall: 0 };
    const server = createServer(async (req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      for (const _ of [req.on('data', () => {})]) void _;
      if (url.pathname === '/healthz') {
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ ok: true, version: 't', host_contract: 1 }));
      }
      if (url.pathname === '/capture') {
        hits.capture += 1;
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ accepted: true, source_id: 's1' }));
      }
      if (url.pathname === '/recall') {
        hits.recall += 1;
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ block, items: [{ id: 'm1' }], suppressed: 0, took_ms: 1 }));
      }
      if (url.pathname === '/persona') {
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ revision: 1, text: '<persona>x</persona>', chars: 20 }));
      }
      res.writeHead(404);
      res.end('{}');
    });
    server.listen(0, '127.0.0.1', () => resolve({ port: server.address().port, hits, close: () => new Promise((r) => server.close(r)) }));
  });
}

function writeRuntime(name, port) {
  const dir = path.join(TMP, name);
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'runtime.json');
  writeFileSync(file, JSON.stringify({ port, token: 't', pid: process.pid, version: 't', host_contract: 1 }), 'utf8');
  return file;
}

const BLOCK = '<relevant-memories>\n- [fact] 键盘延迟与 USB 仲裁有关\n</relevant-memories>';

// ---------- 1. apply 不抛 ----------
{
  for (const cfg of [undefined, null, {}, { enabled: 'yes' }, { budgetChars: 'abc' }, { subjectMode: 'nope' }]) {
    let threw = null;
    try {
      const ctx = fakeCtx();
      apply(ctx, cfg);
    } catch (err) {
      threw = err?.message ?? String(err);
    }
    expect(`apply(${JSON.stringify(cfg)}) 不抛`, threw, null);
  }
}

// ---------- 2. pre-step 真的注入 ----------
const s = await serve({ block: BLOCK });
{
  const ctx = fakeCtx();
  apply(ctx, { runtimePath: writeRuntime('ok', s.port), recallTimeoutMs: 500, subjectMode: 'fixed', subjectKey: 'test:user:1' });
  const preStep = ctx.handlers.get('agent/pre-step')?.[0];
  expect('注册了 agent/pre-step', typeof preStep, 'function');

  const decision = {
    kind: 'enter',
    messages: [{ role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: '键盘又延迟了' }] }],
  };
  const out = await preStep({ messages: decision.messages }, async () => decision);
  expect('注入后多一条消息', out.messages.length, 2);
  const injected = out.messages[0];
  expect('注入消息排在用户消息之前', injected.source?.kind, 'plugin:seekmemory');
  expect('注入内容是内核返回的块', injected.content?.[0]?.text?.includes('键盘延迟'), true);

  // capture 钩子
  const onEvent = ctx.handlers.get('session/event')?.[0];
  expect('注册了 session/event', typeof onEvent, 'function');
  onEvent({ id: 'sess-1' }, { type: 'user/message', time: Date.now(), data: { id: 'm1', content: [{ type: 'text', text: '我回来了' }] } });
  await new Promise((r) => setTimeout(r, 200));
  expect('capture 被调用', s.hits.capture >= 1, true);
}

// ---------- 3. 内核不可用 → 原样返回 ----------
{
  const ctx = fakeCtx();
  apply(ctx, { runtimePath: path.join(TMP, 'nope', 'runtime.json'), recallTimeoutMs: 120, subjectMode: 'fixed', subjectKey: 'k' });
  const preStep = ctx.handlers.get('agent/pre-step')?.[0];
  const decision = { kind: 'enter', messages: [{ role: 'user', source: { kind: 'user' }, content: [{ type: 'text', text: '键盘又延迟了' }] }] };
  const out = await preStep({ messages: decision.messages }, async () => decision);
  expect('内核挂了 → 消息数不变', out.messages.length, 1);
  expect('内核挂了 → 仍是同一条', out.messages[0], decision.messages[0]);
  expect('降级有日志', ctx.logLines.some((l) => l.includes('召回跳过')), true);
}

// ---------- 4. 卸载回收 ----------
{
  const ctx = fakeCtx();
  apply(ctx, { runtimePath: writeRuntime('ok2', s.port), subjectMode: 'fixed', subjectKey: 'k' });
  expect('注册了 effect', ctx.effects.length, 1);
  expect('卸载前有 pre-step', (ctx.handlers.get('agent/pre-step') ?? []).length, 1);
  ctx.effects[0]();
  expect('卸载后 pre-step 被移除', (ctx.handlers.get('agent/pre-step') ?? []).length, 0);
  expect('卸载有日志', ctx.logLines.some((l) => l.includes('已卸载')), true);
}

await s.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
