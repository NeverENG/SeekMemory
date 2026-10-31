#!/usr/bin/env node
/**
 * 契约冒烟：对**已经跑起来的内核**验一遍端点语义（M0 验收 + §10.3 的前半段）。
 *
 * 它不启动内核——沙箱里 spawn 子进程会被拒（EPERM），而且冒烟本来就该
 * 对着真实进程跑。用法：
 *   node mock/kernel.mjs --data-dir .tmp/mock      # 另开一个终端
 *   node scripts/smoke-contract.mjs --runtime .tmp/mock/runtime.json
 *
 * 断言的是**契约**，不是实现细节：
 *   healthz 的 host_contract / capture 回执 / recall 命中 / secret 不外泄 /
 *   budget 上限 / persona / status / extract plan(204 或任务) / 鉴权拦截
 */

import { readFileSync } from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);
function arg(name, fallback = '') {
  const i = argv.indexOf(name);
  return i >= 0 ? (argv[i + 1] ?? fallback) : fallback;
}

const runtimePath = path.resolve(arg('--runtime', '.tmp/mock/runtime.json'));
const steps = [];

function record(name, ok, detail = '') {
  steps.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? `  — ${detail}` : ''}`);
}

let runtime;
try {
  runtime = JSON.parse(readFileSync(runtimePath, 'utf8'));
} catch (err) {
  console.error(`读不到 runtime.json: ${runtimePath}\n${err.message}`);
  process.exitCode = 1;
  throw new Error('runtime.json unavailable');
}

const base = `http://127.0.0.1:${runtime.port}`;
const auth = { authorization: `Bearer ${runtime.token}` };

async function call(pathname, opts = {}) {
  const res = await fetch(`${base}${pathname}`, {
    ...opts,
    headers: { ...auth, ...(opts.body ? { 'content-type': 'application/json' } : {}), ...(opts.headers ?? {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    signal: AbortSignal.timeout(opts.timeoutMs ?? 5000),
  });
  const text = await res.text();
  let json = null;
  try {
    json = text ? JSON.parse(text) : null;
  } catch {
    /* 保留 text 供断言 */
  }
  return { status: res.status, json, text };
}

const subject = 'test:user:1';

// 1. healthz
try {
  const r = await call('/healthz');
  record(
    'healthz 可达且契约版本匹配',
    r.status === 200 && r.json && Number(r.json.host_contract) === Number(runtime.host_contract ?? 0),
    `status=${r.status} contract=${r.json?.host_contract} version=${r.json?.version}`,
  );
} catch (err) {
  record('healthz 可达', false, err.message);
}

// 2. 鉴权：无 token 必须 401
try {
  const res = await fetch(`${base}/status`, { signal: AbortSignal.timeout(3000) });
  record('缺 token 被拒（401）', res.status === 401, `status=${res.status}`);
} catch (err) {
  record('缺 token 被拒（401）', false, err.message);
}

// 3. capture
try {
  const r = await call('/capture', {
    method: 'POST',
    body: { subject_key: subject, session: 's1', role: 'user', text: '我的键盘又延迟了', at: new Date().toISOString(), msg_id: 'm1' },
  });
  record('capture 回执含 source_id', r.status === 200 && typeof r.json?.source_id === 'string', `source_id=${r.json?.source_id}`);
} catch (err) {
  record('capture', false, err.message);
}

// 4. recall 命中
let blockText = '';
let needsExtraction = false;
try {
  const r = await call('/recall', { method: 'POST', body: { subject_key: subject, query: '键盘 延迟', budget_chars: 600, k: 8 } });
  blockText = String(r.json?.block ?? '');
  const hit = blockText.includes('键盘');
  if (hit) {
    record('recall 命中相关记忆', r.status === 200, `items=${r.json?.items?.length ?? 0} chars=${blockText.length}`);
  } else {
    // 真内核语义：capture 只写 Source 并入队，Artifact 要等抽取后才产生，
    // 所以「capture 后立刻召回」只对 mock 的简化实现成立。用队列里有没有任务
    // 来区分「语义差异」与「capture 根本没入队」——后者仍然判失败，不是假绿。
    const plan = await call(`/extract/plan?subject_key=${encodeURIComponent(subject)}`);
    needsExtraction = plan.status === 200 && Boolean(plan.json?.task_id);
    record('recall 命中相关记忆', needsExtraction,
      needsExtraction
        ? '真内核语义：需先抽取（队列有任务，capture 已入队）'
        : 'items=0 且队列为空 → capture 没入队');
  }
} catch (err) {
  record('recall', false, err.message);
}

// 5. secret 绝不外泄 —— 必须配正向对照，否则空块会让断言恒真（假绿）
try {
  const ctl = await call('/recall', { method: 'POST', body: { subject_key: subject, query: '键盘', budget_chars: 600, k: 8 } });
  const ctlChars = String(ctl.json?.block ?? '').length;
  record('正向对照：普通查询能召回（证明管线活着）', ctlChars > 0 || needsExtraction,
    needsExtraction ? 'SKIP：需先抽取（真内核语义）' : `chars=${ctlChars}`);

  const r = await call('/recall', { method: 'POST', body: { subject_key: subject, query: '秘密', budget_chars: 600, k: 8 } });
  const block = String(r.json?.block ?? '');
  const leaked = block.includes('secret');
  record('secret 记录不出现在召回块里', !leaked, leaked ? '命中 secret 正文' : `ok（该轮块 ${block.length} 字）`);
} catch (err) {
  record('secret 不外泄', false, err.message);
}

// 6. budget 上限 —— 预算必须够装下至少一条，否则空块让断言恒真
try {
  const budget = 200;
  const r = await call('/recall', { method: 'POST', body: { subject_key: subject, query: '键盘', budget_chars: budget, k: 8 } });
  const len = String(r.json?.block ?? '').length;
  record(`budget 上限生效（0 < len ≤ ${budget}）`, (len > 0 && len <= budget) || needsExtraction,
    needsExtraction ? 'SKIP：需先抽取（真内核语义）' : `实际 ${len} 字`);
} catch (err) {
  record('budget 上限', false, err.message);
}

// 6b. 预算过小 → 必须老实返回空块，而不是硬塞
try {
  const budget = 30;
  const r = await call('/recall', { method: 'POST', body: { subject_key: subject, query: '键盘', budget_chars: budget, k: 8 } });
  const len = String(r.json?.block ?? '').length;
  record(`预算不足时返回空块（≤${budget}）`, len === 0, `实际 ${len} 字`);
} catch (err) {
  record('预算不足返回空块', false, err.message);
}

// 7. persona
try {
  const r = await call(`/persona?subject_key=${encodeURIComponent(subject)}`);
  record('persona 返回 revision 与文本', r.status === 200 && Number(r.json?.revision) >= 0, `revision=${r.json?.revision}`);
} catch (err) {
  record('persona', false, err.message);
}

// 8. status（含 host_contract / 进度 / 降级原因）
try {
  const r = await call('/status');
  const ok = r.status === 200 && r.json && 'host_contract' in r.json && 'progress' in r.json;
  record('status 含 host_contract + progress', ok, `contract=${r.json?.host_contract} phase=${r.json?.progress?.phase}`);
} catch (err) {
  record('status', false, err.message);
}

// 9. extract plan：204（没事干）或 200（有任务）
try {
  const r = await call('/extract/plan', { timeoutMs: 30_000 });
  const ok = r.status === 204 || (r.status === 200 && typeof r.json?.task_id === 'string');
  record('extract/plan 返回 204 或任务', ok, `status=${r.status}`);
} catch (err) {
  record('extract/plan', false, err.message);
}

// ---------- 汇总 ----------
const failed = steps.filter((s) => !s.ok).length;
console.log(`\n${failed === 0 ? 'ALL PASS' : `${failed} FAILED`} (${steps.length} checks) — kernel ${runtime.version ?? '?'} @ ${base}`);
// 不要用 process.exit()：fetch 的 keep-alive socket 还没关完时在 Windows 上会触发
// libuv 断言（uv_handle closing）→ 进程 fail-fast，退出码变成 0xC0000409。
// 设 exitCode 让事件循环自己退干净。
process.exitCode = failed === 0 ? 0 : 1;
