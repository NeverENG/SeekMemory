#!/usr/bin/env node
/**
 * M5 抽取桥测试：拉取式（plan → 宿主 LLM → commit）。
 *
 * 最关键的一条断言是 **block-end 权威**：宿主流同时给 text-delta 和 block-end 时，
 * 只取后者，否则正文会翻倍（上游踩过，见 llm.d.ts:146-148）。
 *
 * 另外覆盖三种"模型侧不可用"的真实路径，它们都必须 skip 而不是崩、也不能提交：
 *   - 未配 provider/model（不猜宿主默认模型）
 *   - 宿主流被中止（finish.reason.kind === 'aborted'）
 *   - 宿主流抛错（provider 侧异常）
 *
 * 用进程内 HTTP 服务当内核，假 llm 服务当宿主，不 spawn、不联网。
 */

import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { KernelClient } from '../src/kernel-client.js';
import { runOnce } from '../src/extract-bridge.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'extract');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = JSON.stringify(actual) === JSON.stringify(wanted);
  results.push({ ok, name });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${JSON.stringify(wanted)} / 实际 ${JSON.stringify(actual)}`);
}

// ---------- 假内核 ----------
// planDecider 由每个用例设置：返回 task 对象，或 null 表示 204。
const commits = [];
let planDecider = () => null;

const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  if (url.pathname === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ ok: true, version: 't', host_contract: 1 }));
  }
  if (url.pathname === '/extract/plan') {
    const task = planDecider();
    if (!task) {
      res.writeHead(204);
      return res.end();
    }
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify(task));
  }
  if (url.pathname === '/extract/commit') {
    const chunks = [];
    for await (const c of req) chunks.push(c);
    commits.push(JSON.parse(Buffer.concat(chunks).toString('utf8')));
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end(JSON.stringify({ written: 1, skipped: 0 }));
  }
  res.writeHead(404);
  res.end('{}');
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;

const runtimePath = path.join(TMP, 'runtime.json');
writeFileSync(runtimePath, JSON.stringify({ port, token: 't', pid: 1, version: 't', host_contract: 1 }), 'utf8');

const task = (id) => ({
  task_id: id,
  chat_request: { system_prompt: 'sys', prompt: '请输出 JSON', max_tokens: 100, temperature: 0 },
});

// ---------- 假宿主 ----------
const log = { info() {}, warn() {}, error() {}, debug() {} };
function fakeCtx(streamFactory) {
  return {
    logger: log,
    get(name) {
      if (name === 'llm') return { stream: streamFactory };
      return undefined;
    },
  };
}

const baseCfg = {
  runtimePath,
  hostContract: 1,
  recallTimeoutMs: 500,
  captureTimeoutMs: 500,
  budgetChars: 600,
  k: 8,
  logPrefix: '[test]',
  subjectKey: 's',
};
const kernel = new KernelClient({ config: baseCfg, logger: log });
const llmCfg = { ...baseCfg, llmProvider: 'p', llmModel: 'm', subjectKey: 's' };

// 1. 正常路径：取活 → 宿主 LLM → 交回
{
  planDecider = () => task('t1');
  const streamFactory = () =>
    (async function* () {
      yield { type: 'text-delta', text: '[' };
      yield { type: 'block-end', block: { type: 'text', text: '[]' } };
      yield { type: 'usage', usage: { inputTokens: 10, outputTokens: 2 } };
      yield { type: 'finish', reason: { kind: 'stop' } };
    })();
  const r = await runOnce({ ctx: fakeCtx(streamFactory), config: llmCfg, kernel, logger: log });
  expect('第一次 runOnce → done', r.outcome, 'done');
  expect('commit 被调用一次', commits.length, 1);
  expect('task_id 正确', commits[0]?.task_id, 't1');
  expect('正文只取 block-end（不翻倍）', commits[0]?.chat_response?.text, '[]');
  expect('用量透传', [commits[0]?.chat_response?.usage_in, commits[0]?.chat_response?.usage_out], [10, 2]);
}

// 2. 没配 provider/model → 跳过，不提交、不丢任务
{
  planDecider = () => task('t2');
  const r = await runOnce({ ctx: fakeCtx(() => (async function* () {})()), config: { ...baseCfg, llmProvider: '', llmModel: '', subjectKey: 's' }, kernel, logger: log });
  expect('未配模型 → skipped', r.outcome, 'skipped');
  expect('未配模型 → 不提交', commits.length, 1);
  expect('跳过原因可读', String(r.detail).includes('llmProvider'), true);
}

// 3. 宿主流被中止（finish.reason.kind = 'aborted'）→ 跳过，不提交
{
  planDecider = () => task('t3');
  const abortedStream = () =>
    (async function* () {
      yield { type: 'text-delta', text: '半截输出' };
      yield { type: 'finish', reason: { kind: 'aborted' } };
    })();
  const r = await runOnce({ ctx: fakeCtx(abortedStream), config: llmCfg, kernel, logger: log });
  expect('流被中止 → skipped', r.outcome, 'skipped');
  expect('中止原因可见', String(r.detail).includes('llm_finish_aborted'), true);
  expect('中止 → 不提交', commits.length, 1);
}

// 4. 宿主流抛错（provider 侧异常）→ 跳过，不提交
{
  planDecider = () => task('t4');
  const throwingStream = () =>
    (async function* () {
      yield { type: 'text-delta', text: '前缀' };
      throw new Error('provider exploded');
    })();
  const r = await runOnce({ ctx: fakeCtx(throwingStream), config: llmCfg, kernel, logger: log });
  expect('流抛错 → skipped', r.outcome, 'skipped');
  expect('抛错原因可见', String(r.detail).includes('llm_throw'), true);
  expect('抛错 → 不提交', commits.length, 1);
}

// 5. 宿主没有 llm 服务 → 跳过（不是崩）
{
  planDecider = () => task('t5');
  const noLlm = { logger: log, get: () => undefined };
  const r = await runOnce({ ctx: noLlm, config: llmCfg, kernel, logger: log });
  expect('宿主无 llm 服务 → skipped', r.outcome, 'skipped');
  expect('无 llm 服务原因可见', String(r.detail).includes('no_llm_service'), true);
  expect('无 llm 服务 → 不提交', commits.length, 1);
}

// 6. 内核 204 → idle
{
  planDecider = () => null;
  const r = await runOnce({ ctx: fakeCtx(() => (async function* () {})()), config: llmCfg, kernel, logger: log });
  expect('无任务 → idle', r.outcome, 'idle');
}

await new Promise((r) => server.close(r));
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
