import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { setTimeout as pause } from 'node:timers/promises';
import test from 'node:test';
import { apply } from '../src/index.js';

const fixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/runtime_host.json', import.meta.url), 'utf8'));

function host() {
  const handlers = new Map();
  const effects = [];
  const logs = [];
  return {
    handlers, effects, logs,
    logger: Object.fromEntries(['debug', 'info', 'warn', 'error'].map((key) => [key, (message) => logs.push(message)])),
    get() {},
    on(name, fn) {
      if (!handlers.has(name)) handlers.set(name, []);
      handlers.get(name).push(fn);
      return () => handlers.set(name, handlers.get(name).filter((item) => item !== fn));
    },
    effect(fn) { effects.push(fn()); },
    dispose() { for (const release of effects.splice(0)) release(); },
  };
}

async function setup(t, { version = 1, hostContract = 1, runtimeStatus = 200, gate = false,
  contextWait, eventWait, injectRecall = true } = {}) {
  const calls = [];
  const server = createServer(async (req, res) => {
    const route = new URL(req.url, 'http://127.0.0.1').pathname;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const body = chunks.length ? JSON.parse(Buffer.concat(chunks).toString()) : null;
    calls.push({ route, body, auth: req.headers.authorization });
    let data = {};
    let status = 200;
    if (route === '/healthz') data = { host_contract: hostContract, version: 'test',
      ...(version === null ? {} : { runtime_contract: version }), runtime_gate_enabled: gate };
    else if (route === '/runtime/events') {
      if (eventWait) await eventWait;
      status = runtimeStatus;
      data = body.kind === 'accept_user' ? { ...fixture.receipt,
        decision: gate ? { ...fixture.receipt.decision, action: 'wait', must_reply: false } : fixture.receipt.decision } : fixture.reply;
    } else if (route === '/runtime/context') {
      if (contextWait) await contextWait;
      data = fixture.context;
    } else if (route === '/recall') data = { block: 'legacy-memory' };
    else if (route === '/capture') data = { accepted: true, source_id: 'legacy-source' };
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(JSON.stringify(data));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-runtime-host-'));
  const runtimePath = path.join(dir, 'runtime.json');
  writeFileSync(runtimePath, JSON.stringify({ port: server.address().port, token: 'test-only-token' }));
  const ctx = host();
  const config = { runtimePath, logDir: dir, stateDir: dir, injectPersona: false, injectRecall,
    subjectMode: 'fixed', subjectKey: fixture.input.speaker_id, captureTimeoutMs: 300, recallTimeoutMs: 500 };
  apply(ctx, config);
  t.after(async () => {
    ctx.dispose();
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
    rmSync(dir, { recursive: true, force: true });
  });
  return { ctx, config, calls };
}

async function until(predicate) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (predicate()) return;
    await pause(5);
  }
  throw new Error('host boundary did not complete');
}

function user(ctx, id = 'event-1') {
  const session = { id: fixture.input.session_id };
  const message = { id, role: 'user', content: fixture.input.text, source: { kind: 'user' } };
  ctx.handlers.get('session/event')[0](session, {
    type: 'user/message', time: 10_000, data: { id, text: fixture.input.text, mentioned: true },
  });
  const decision = { kind: 'enter', messages: [message], usage: { retained: true } };
  return { session, decision, payload: { agent: { session }, messages: [message] } };
}

test('production hooks use runtime capture/context and never mark a generated reply delivered', async (t) => {
  const { ctx, calls } = await setup(t);
  const turn = user(ctx);
  const result = await ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.equal(result.messages[0].content[0].text, fixture.context.text);
  assert.deepEqual(result.usage, turn.decision.usage);
  const context = calls.find((call) => call.route === '/runtime/context').body;
  assert.equal(context.source_id, fixture.receipt.source_id);
  assert.equal(context.event_time, 10);
  assert.equal(calls.filter((call) => call.route === '/capture').length, 0);
  ctx.handlers.get('session/event')[0](turn.session, {
    type: 'assistant/message', time: 15_000, data: { id: 'answer-1', text: '你好' },
  });
  await until(() => calls.some((call) => call.body?.kind === 'record_reply'));
  assert.equal(calls.some((call) => call.body?.kind === 'record_delivery'), false);
  assert.ok(calls.filter((call) => call.route.startsWith('/runtime/')).every((call) => call.auth === 'Bearer test-only-token'));
});

test('legacy service keeps capture and recall; runtime write failure never retries legacy capture', async (t) => {
  const legacy = await setup(t, { version: null });
  const turn = user(legacy.ctx);
  const result = await legacy.ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.equal(result.messages[0].content[0].text, 'legacy-memory');
  assert.equal(legacy.calls.filter((call) => call.route === '/capture').length, 1);
  const broken = await setup(t, { runtimeStatus: 500 });
  user(broken.ctx);
  await until(() => broken.calls.some((call) => call.route === '/runtime/events'));
  await pause(20);
  assert.equal(broken.calls.some((call) => call.route === '/capture'), false);
});

test('host gate follows server opt-in and its decision without a local attention policy', async (t) => {
  const { ctx, calls } = await setup(t, { gate: true });
  const turn = user(ctx);
  const result = await ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.deepEqual(result, { ...turn.decision, kind: 'reject' });
  assert.equal(calls.some((call) => call.route === '/runtime/context'), false);
});

test('duplicate apply registers once; unloading prevents late injection and permits a fresh apply', async (t) => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const { ctx, config, calls } = await setup(t, { contextWait: waiting });
  apply(ctx, config);
  assert.equal(ctx.handlers.get('session/event').length, 1);
  assert.equal(ctx.effects.length, 1);
  const turn = user(ctx);
  const pending = ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  await until(() => calls.some((call) => call.route === '/runtime/context'));
  ctx.dispose();
  release();
  assert.strictEqual(await pending, turn.decision);
  assert.equal(ctx.handlers.get('session/event').length, 0);
  apply(ctx, config);
  assert.equal(ctx.handlers.get('session/event').length, 1);
});

test('an in-flight capture at shutdown never claims evidence was not written or retries it', async (t) => {
  let release;
  const waiting = new Promise((resolve) => { release = resolve; });
  const { ctx, calls } = await setup(t, { eventWait: waiting });
  user(ctx);
  await until(() => calls.some((call) => call.body?.kind === 'accept_user'));
  ctx.dispose();
  release();
  await until(() => ctx.logs.some((line) => line.includes('捕获失败 reason=runtime_stopped')));
  const warning = ctx.logs.find((line) => line.includes('捕获失败 reason=runtime_stopped'));
  assert.match(warning, /写入结果未知/);
  assert.doesNotMatch(warning, /没进记忆/);
  assert.equal(calls.some((call) => call.route === '/capture'), false);
});

test('a repeated old disposer cannot remove the new instances registration marker', async (t) => {
  const { ctx, config } = await setup(t);
  const oldDispose = ctx.effects[0];
  oldDispose();
  apply(ctx, config);
  oldDispose();
  apply(ctx, config);
  assert.equal(ctx.handlers.get('session/event').length, 1);
  assert.equal(ctx.handlers.get('agent/pre-step').length, 1);
});

test('base contract mismatch never falls back to unverified memory injection', async (t) => {
  const { ctx, calls } = await setup(t, { hostContract: 2 });
  const turn = user(ctx);
  const result = await ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.strictEqual(result, turn.decision);
  assert.equal(calls.some((call) => ['/capture', '/recall', '/runtime/context'].includes(call.route)), false);
});

test('fallback decision messages carry their own receipt and original event time', async (t) => {
  const { ctx, calls } = await setup(t);
  const turn = user(ctx);
  turn.payload.messages = [];
  const result = await ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.equal(result.messages[0].content[0].text, fixture.context.text);
  const input = calls.find((call) => call.body?.kind === 'accept_user').body.input;
  const request = calls.find((call) => call.route === '/runtime/context').body;
  assert.equal(request.source_id, fixture.receipt.source_id);
  assert.equal(request.event_time, input.event_time);
  assert.equal(request.received_at, input.received_at);
});

test('disabling memory injection does not disable the independent server runtime gate', async (t) => {
  const { ctx, calls } = await setup(t, { gate: true, injectRecall: false });
  const turn = user(ctx);
  const result = await ctx.handlers.get('agent/pre-step')[0](turn.payload, async () => turn.decision);
  assert.deepEqual(result, { ...turn.decision, kind: 'reject' });
  assert.equal(calls.some((call) => ['/runtime/context', '/recall'].includes(call.route)), false);
});
