#!/usr/bin/env node
/**
 * 客户端 fail-open 测试（G14）。
 *
 * 每个故障用一个**进程内**极小 HTTP 服务模拟——不 spawn 子进程
 * （沙箱里 spawn 不可靠，见 ENGINEERING-NOTES D1），也不依赖内核。
 *
 * 断言的是"降级原因是可区分、可上报的枚举"，不是"没崩"：
 * 只要有一种故障被混成 exception，状态面板就再也说不清为什么记忆没生效。
 */

import { createServer } from 'node:http';
import { mkdirSync, writeFileSync, rmSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { KernelClient } from '../src/kernel-client.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const TMP = path.join(ROOT, '.tmp', 'failopen');
rmSync(TMP, { recursive: true, force: true });
mkdirSync(TMP, { recursive: true });

const results = [];
function expect(name, actual, wanted) {
  const ok = actual === wanted;
  results.push({ ok, name, actual, wanted });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}  — 期望 ${wanted} / 实际 ${actual}`);
}

/** 起一个行为可配置的小服务，返回 {port, close}。 */
function serve(behavior) {
  return new Promise((resolve) => {
    const server = createServer(async (req, res) => {
      const url = new URL(req.url, 'http://127.0.0.1');
      if (behavior === 'unauthorized') {
        res.writeHead(401, { 'content-type': 'application/json' });
        return res.end('{"error":"unauthorized"}');
      }
      if (behavior === 'boom') {
        res.writeHead(500, { 'content-type': 'application/json' });
        return res.end('{"error":"boom"}');
      }
      if (behavior === 'slow') {
        await new Promise((r) => setTimeout(r, 1200));
      }
      if (behavior === 'badcontract' && url.pathname === '/healthz') {
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ ok: true, version: 'x', host_contract: 9 }));
      }
      if (url.pathname === '/healthz') {
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ ok: true, version: 'test', host_contract: 1 }));
      }
      if (url.pathname === '/recall') {
        res.writeHead(200, { 'content-type': 'application/json' });
        return res.end(JSON.stringify({ block: '<relevant-memories>\n- [fact] 键盘延迟\n</relevant-memories>', items: [], suppressed: 0, took_ms: 1 }));
      }
      res.writeHead(404);
      res.end('{}');
    });
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ port, close: () => new Promise((r) => server.close(r)) });
    });
  });
}

function writeRuntime(name, port, contract = 1) {
  const dir = path.join(TMP, name);
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'runtime.json');
  writeFileSync(
    file,
    JSON.stringify({ port, token: 't', pid: process.pid, version: 'test', host_contract: contract }),
    'utf8',
  );
  return file;
}

const log = { info() {}, warn() {}, error() {}, debug() {} };
const baseCfg = { runtimePath: '', dataDir: '', hostContract: 1, recallTimeoutMs: 150, captureTimeoutMs: 150, budgetChars: 600, k: 8, logPrefix: '[test]' };

// 1. 没有 runtime.json
{
  const file = path.join(TMP, 'missing', 'runtime.json');
  mkdirSync(path.dirname(file), { recursive: true });
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: file }, logger: log });
  const r = await c.recall({ query: 'x', subjectKey: 's' });
  expect('缺 runtime.json → no_runtime_file', r.reason, 'no_runtime_file');
}

// 2. 401
{
  const s = await serve('unauthorized');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: writeRuntime('unauth', s.port) }, logger: log });
  const r = await c.recall({ query: 'x', subjectKey: 's' });
  expect('token 错 → http_401', r.reason, 'http_401');
  await s.close();
}

// 3. 500
{
  const s = await serve('boom');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: writeRuntime('boom', s.port) }, logger: log });
  const r = await c.recall({ query: 'x', subjectKey: 's' });
  expect('内核 500 → http_500', r.reason, 'http_500');
  await s.close();
}

// 4. 超时
{
  const s = await serve('slow');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: writeRuntime('slow', s.port) }, logger: log });
  const r = await c.recall({ query: 'x', subjectKey: 's' });
  expect('内核慢过预算 → timeout', r.reason, 'timeout');
  await s.close();
}

// 5. 契约不匹配（只 health 检）
{
  const s = await serve('badcontract');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: writeRuntime('badc', s.port, 9) }, logger: log });
  const r = await c.health();
  expect('契约版本不符 → contract_mismatch', r.reason, 'contract_mismatch');
  await s.close();
}

// 6. 正常路径
{
  const s = await serve('ok');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: writeRuntime('ok', s.port) }, logger: log });
  const h = await c.health();
  expect('健康检查通过', h.ok, true);
  const r = await c.recall({ query: '键盘', subjectKey: 's' });
  expect('召回返回 block', r.ok && typeof r.data?.block === 'string', true);
  expect('降级状态已清空', c.degraded, null);
  await s.close();
}

// 7. 非法端口：以前只有 typeof 校验，99999 能过 → new URL() 抛 → 宿主被杀
{
  const dir = path.join(TMP, 'badport');
  mkdirSync(dir, { recursive: true });
  const file = path.join(dir, 'runtime.json');
  writeFileSync(file, JSON.stringify({ port: 99999, token: 't', pid: 1, version: 'x', host_contract: 1 }), 'utf8');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: file }, logger: log });
  let threw = null;
  let r;
  try {
    r = await c.recall({ query: 'x', subjectKey: 's' });
  } catch (err) {
    threw = err?.message ?? String(err);
  }
  expect('端口非法 → 不抛异常（回归：阻断项）', threw, null);
  expect('端口非法 → bad_runtime_file', r?.reason, 'bad_runtime_file');
}

// 8. 端口是字符串但合法：应当接受（避免误判成无内核）
{
  const dir = path.join(TMP, 'strport');
  mkdirSync(dir, { recursive: true });
  const s = await serve('ok');
  const file = path.join(dir, 'runtime.json');
  writeFileSync(file, JSON.stringify({ port: String(s.port), token: 't', pid: 1, version: 'x', host_contract: 1 }), 'utf8');
  const c = new KernelClient({ config: { ...baseCfg, runtimePath: file }, logger: log });
  const r = await c.recall({ query: 'x', subjectKey: 's' });
  expect('字符串端口被接受', r.ok, true);
  await s.close();
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks)`);
process.exitCode = failed === 0 ? 0 : 1;
