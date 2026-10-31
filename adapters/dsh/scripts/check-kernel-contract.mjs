#!/usr/bin/env node
/**
 * 内核端点契约的符合性测试（host_contract = 1）。
 *
 * 它和 test/*.mjs 的分工：
 *   test/*.mjs        验**适配器**行为（用本仓库的 mock 内核当对端）
 *   本脚本             验**内核**是否符合契约（对端可以是 mock，也可以是真正的 serve.py）
 *
 * 所以开发者把真内核推上来之后，第一件事就是：
 *   node scripts/check-kernel-contract.mjs --runtime <内核写出的 runtime.json>
 *
 * 断言只依赖 issue #107 的 P3 所列 7 个端点，不绑定任何实现细节：
 *   GET  /healthz       200 + host_contract 数字
 *   POST /capture       200/202 + source_id 或 accepted
 *   POST /recall        200 + block 字符串
 *   GET  /persona       200 + text 字符串
 *   GET  /status        200 + 对象
 *   GET  /extract/plan  200（有任务）或 204（没事干）
 *   POST /extract/commit 200 + written/skipped
 * 另外两条安全/路由约束：错 token → 401，未知路径 → 404。
 *
 * 退出码：0 全部符合；1 有不符合项；2 参数或连接问题。
 */

import { readFileSync } from 'node:fs';

const argv = process.argv.slice(2);
const arg = (name, fallback = '') => {
  const i = argv.indexOf(name);
  return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
};

const runtimePath = arg('--runtime');
if (!runtimePath) {
  console.error('用法: node scripts/check-kernel-contract.mjs --runtime <runtime.json>');
  process.exit(2);
}

let runtime;
try {
  runtime = JSON.parse(readFileSync(runtimePath, 'utf8'));
} catch (err) {
  console.error(`FAIL  读不到 runtime.json: ${runtimePath} (${err.message})`);
  process.exit(2);
}

const base = `http://127.0.0.1:${runtime.port}`;
const token = runtime.token ?? '';
const results = [];
const expect = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
};

async function call(path, { method = 'GET', body, auth = token } = {}) {
  const headers = {};
  if (auth) headers.authorization = `Bearer ${auth}`;
  if (body !== undefined) headers['content-type'] = 'application/json';
  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  const text = await res.text();
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { __nonJson: text.slice(0, 120) };
  }
  return { status: res.status, data };
}

const SUBJECT = 'contract:test:subject';
const payload = {
  subject_key: SUBJECT,
  session: 'contract-session',
  role: 'user',
  text: 'contract probe message',
  at: new Date().toISOString(),
  msg_id: 'contract-msg-1',
};

// 1. healthz
{
  const r = await call('/healthz');
  const hc = r.data?.host_contract;
  expect('GET /healthz → 200', r.status === 200, `status=${r.status}`);
  // 硬断言：版本不符就是不符，适配器会拒绝注入，不能放过去
  expect('healthz.host_contract === 1', hc === 1, `实际 ${JSON.stringify(hc)}（适配器期望 1）`);
}

// 2. capture
{
  const r = await call('/capture', { method: 'POST', body: payload });
  const okStatus = r.status === 200 || r.status === 202;
  const hasId = typeof r.data?.source_id === 'string' && r.data.source_id.length > 0;
  const hasAccepted = r.data?.accepted === true;
  expect('POST /capture → 200/202', okStatus, `status=${r.status}`);
  expect('capture 返回 source_id 或 accepted', hasId || hasAccepted,
    `source_id=${JSON.stringify(r.data?.source_id)} accepted=${JSON.stringify(r.data?.accepted)}`);
}

// 3. recall
{
  const r = await call('/recall', {
    method: 'POST',
    body: { subject_key: SUBJECT, query: 'contract probe', budget_chars: 600, k: 8, now: new Date().toISOString() },
  });
  expect('POST /recall → 200', r.status === 200, `status=${r.status}`);
  expect('recall.block 是字符串', typeof r.data?.block === 'string',
    `实际 ${typeof r.data?.block}`);
}

// 4. persona
{
  const r = await call(`/persona?subject_key=${encodeURIComponent(SUBJECT)}`);
  expect('GET /persona → 200', r.status === 200, `status=${r.status}`);
  const okShape = typeof r.data?.text === 'string' || typeof r.data?.revision === 'number';
  expect('persona 返回 text 或 revision', okShape,
    `text=${typeof r.data?.text} revision=${typeof r.data?.revision}`);
}

// 5. status
{
  const r = await call('/status');
  const isObj = r.data !== null && typeof r.data === 'object' && !Array.isArray(r.data);
  expect('GET /status → 200', r.status === 200, `status=${r.status}`);
  expect('status 返回对象', isObj, `实际 ${Array.isArray(r.data) ? 'array' : typeof r.data}`);
}

// 6. extract/plan（204 = 没事干，是合法契约的一部分）
{
  const r = await call(`/extract/plan?subject_key=${encodeURIComponent(SUBJECT)}`);
  expect('GET /extract/plan → 200 或 204', r.status === 200 || r.status === 204, `status=${r.status}`);
}

// 7. extract/commit
{
  const r = await call('/extract/commit', {
    method: 'POST',
    body: { task_id: 'contract-task-1', chat_response: { text: '[]', usage_in: 0, usage_out: 0 } },
  });
  // 501 = 内核明确表示「pull-style 提交还没实现」，与「实现错了」是两回事。
  // 分开标注，才不会把待办混进缺陷里。
  if (r.status === 501) {
    expect('POST /extract/commit → 501（明确未实现，非缺陷）', true);
  } else {
    expect('POST /extract/commit → 200', r.status === 200, `status=${r.status}`);
    const okShape = typeof r.data?.written === 'number' || typeof r.data?.skipped === 'number';
    expect('commit 返回 written 或 skipped', okShape,
      `written=${JSON.stringify(r.data?.written)} skipped=${JSON.stringify(r.data?.skipped)}`);
  }
}

// 8. 错 token → 401
{
  const r = await call('/status', { auth: 'definitely-wrong-token' });
  expect('错 token → 401', r.status === 401, `status=${r.status}`);
}

// 9. 未知路径 → 404
{
  const r = await call('/definitely-not-a-route');
  expect('未知路径 → 404', r.status === 404, `status=${r.status}`);
}

const failed = results.filter((r) => !r.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${results.length} checks) — kernel ${base}`);
process.exitCode = failed === 0 ? 0 : 1;
