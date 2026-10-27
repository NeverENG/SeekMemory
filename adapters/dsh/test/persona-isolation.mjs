#!/usr/bin/env node
/**
 * 隐私回归：人格块必须**按主体隔离**。
 *
 * 背景（review #110 第 1 条）：persona 原先是模块级单槽缓存，只查 TTL 不查 subject，
 * 导致 A 的画像在 60s 内会被注入到 B 的上下文里。这是身份/隐私 bug。
 *
 * 本用例造两个主体 A/B，各自的 /persona 返回不同文本，断言：
 *   1. A 的 context.text() 只含 A 的画像
 *   2. B 的 context.text() 只含 B 的画像
 *   3. 先刷新 A 再刷新 B，A 的内容不被 B 覆盖（这正是单槽缓存的失效形态）
 */

import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { apply } from '../src/index.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'persona-isolation');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

// ---------- 假内核：/persona 按 subject 返回不同内容 ----------
const server = createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  const json = (code, obj) => {
    res.writeHead(code, { 'content-type': 'application/json' });
    res.end(JSON.stringify(obj));
  };
  if (url.pathname === '/healthz') return json(200, { ok: true, version: 't', host_contract: 1 });
  if (url.pathname === '/persona') {
    const sk = url.searchParams.get('subject_key') ?? '';
    return json(200, { revision: 1, text: `<persona>${sk}</persona>`, chars: sk.length });
  }
  if (url.pathname === '/recall') return json(200, { block: '', items: [], suppressed: 0, took_ms: 0 });
  if (url.pathname === '/capture') return json(200, { accepted: true, source_id: 's' });
  json(404, {});
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const runtimePath = path.join(TMP, 'runtime.json');
writeFileSync(runtimePath, JSON.stringify({ port, token: 't', pid: 1, version: 't', host_contract: 1 }), 'utf8');

// ---------- 假宿主 ----------
const log = { info() {}, warn() {}, error() {}, debug() {} };
const contexts = new Map(); // agentId -> text 访问器
const handlers = new Map();
const ctx = {
  logger: log,
  on(name, fn) {
    handlers.set(name, fn);
    return () => {};
  },
  effect() {},
  get(name) {
    if (name === 'agents') return { list: () => [] };
    return undefined;
  },
};

function makeAgent(id, umo) {
  return {
    id,
    // 主体键走 auto 模式：从 session 元数据里取
    session: { id: `sess-${id}`, umo },
    ctx: {
      systemPrompt: {
        context(opts) {
          contexts.set(id, opts.text);
          return () => {};
        },
      },
    },
  };
}

apply(ctx, { runtimePath, stateDir: TMP, logDir: TMP, subjectMode: 'auto', recallTimeoutMs: 300 });

const onCreated = handlers.get('agent/created');
const A = makeAgent('agentA', 'subject:A');
const B = makeAgent('agentB', 'subject:B');

await onCreated({ agent: A });
await onCreated({ agent: B });
// 等两次 /persona 异步刷新落地
await new Promise((r) => setTimeout(r, 400));

const textA = contexts.get('agentA');
const textB = contexts.get('agentB');
expect('两个 agent 各自注册了 context', [typeof textA, typeof textB], ['function', 'function']);

const a = textA ? textA() : '';
const b = textB ? textB() : '';
expect('A 的上下文含 A 的画像', a.includes('subject:A'), true);
expect('A 的上下文不含 B 的画像', a.includes('subject:B'), false);
expect('B 的上下文含 B 的画像', b.includes('subject:B'), true);
expect('B 的上下文不含 A 的画像', b.includes('subject:A'), false);
expect('A/B 文本不相同（没有被单槽覆盖）', a === b, false);

await new Promise((r) => server.close(r));
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
