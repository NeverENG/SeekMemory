import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as pause } from 'node:timers/promises';
import test from 'node:test';
import { normalize } from '../src/config.js';
import { KernelClient } from '../src/kernel-client.js';
import { RuntimeBridge, runtimeInput } from '../src/runtime-bridge.js';

const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const cli = fileURLToPath(new URL('../../../scripts/serve.py', import.meta.url));
const contract = fileURLToPath(new URL('../scripts/check-kernel-contract.mjs', import.meta.url));
const smoke = fileURLToPath(new URL('../scripts/smoke-contract.mjs', import.meta.url));

test('real loopback commits a task but reports unextracted recall as incomplete',
  { timeout: 20_000 }, async (t) => {
    const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-loopback-contract-'));
    const child = spawn(python, [cli, '--data-dir', dir, '--port', '0', '--quiet'], {
      stdio: 'ignore', windowsHide: true,
    });
    const exited = new Promise((resolve) => child.once('exit', resolve));
    t.after(async () => { child.kill(); await exited; rmSync(dir, { recursive: true, force: true }); });
    const runtimePath = path.join(dir, 'runtime.json');
    let endpoint;
    for (let attempt = 0; attempt < 150; attempt += 1) {
      try { endpoint = JSON.parse(readFileSync(runtimePath, 'utf8')); break; }
      catch { await pause(20); }
    }
    assert.equal(endpoint?.host_contract, 1, 'CLI must publish the endpoint');
    const checked = spawnSync(process.execPath, [contract, '--runtime', runtimePath, '--subject', 'loopback:default'], {
      encoding: 'utf8', timeout: 10_000, windowsHide: true,
    });
    assert.equal(checked.status, 0, checked.stdout + checked.stderr);
    assert.match(checked.stdout, /ALL PASS/);
    const observed = spawnSync(process.execPath, [smoke, '--runtime', runtimePath, '--subject', 'loopback:default'], {
      encoding: 'utf8', timeout: 10_000, windowsHide: true,
    });
    assert.equal(observed.status, 2, observed.stdout + observed.stderr);
    assert.match(observed.stdout, /INCOMPLETE/);
    assert.doesNotMatch(observed.stdout, /ALL PASS/);
  });


test('real DSH loopback runtime keeps legacy Source identity and disclosed context',
  { timeout: 20_000 }, async (t) => {
    const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-live-dsh-runtime-'));
    const child = spawn(python, [cli, '--data-dir', dir, '--port', '0', '--quiet'], {
      stdio: 'ignore', windowsHide: true,
    });
    const exited = new Promise((resolve) => child.once('exit', resolve));
    t.after(async () => { child.kill(); await exited; rmSync(dir, { recursive: true, force: true }); });
    const runtimePath = path.join(dir, 'runtime.json');
    let endpoint;
    for (let attempt = 0; attempt < 150; attempt += 1) {
      try { endpoint = JSON.parse(readFileSync(runtimePath, 'utf8')); break; }
      catch { await pause(20); }
    }
    assert.equal(endpoint?.host_contract, 1);
    const { config } = normalize({ runtimePath, captureTimeoutMs: 2000, recallTimeoutMs: 2000 });
    const client = new KernelClient({ config });
    const bridge = new RuntimeBridge(client);
    t.after(() => bridge.stop());
    const health = await client.health();
    assert.equal(health.data.runtime_contract, 1);
    assert.equal(health.data.runtime_gate_enabled, false);
    const subject = 'loopback:default';
    const sessionId = 'dsh-live-session';
    const eventTime = Date.parse('2026-11-05T00:00:00.000Z') / 1000;
    const input = runtimeInput({ sessionId, value: 'hello?', speakerId: subject,
      privateChat: true, eventTime, receivedAt: eventTime, eventId: 'live-u1' });
    const accepted = await bridge.event('accept_user', subject, { input, event_id: 'live-u1' });
    assert.equal(accepted.ok, true);
    assert.equal(accepted.data.decision.action, 'reply');
    assert.equal(accepted.data.turn_id, 'live-u1');
    const legacy = await client.capture({ subject_key: subject, session: sessionId,
      role: 'user', text: input.text, msg_id: 'live-u1', at: new Date(eventTime * 1000).toISOString() });
    assert.equal(legacy.ok, true);
    assert.equal(legacy.data.source_id, accepted.data.source_id);
    const reply = await bridge.event('record_reply', subject, {
      session_id: sessionId, text: 'hi', speaker_id: 'assistant', turn_id: 'live-a1',
      reply_to: accepted.data.source_id, at: '2026-11-05T00:00:05.000Z', recall_ids: [],
    });
    assert.equal(reply.ok, true);
    const oldReply = await client.capture({ subject_key: subject, session: sessionId, role: 'assistant',
      speaker: 'assistant', text: 'hi', msg_id: 'live-a1', at: '2026-11-05T00:00:05.000Z',
      reply_to: accepted.data.source_id });
    assert.equal(oldReply.data.source_id, reply.data.assistant_source_id);
    const context = await bridge.context(subject, { sessionId, value: 'hello?',
      speakerId: subject, privateChat: true, budgetChars: 2, k: 1 });
    assert.equal(context.ok, true);
    assert.equal(typeof context.data.text, 'string');
    assert.equal(typeof context.data.info, 'object');
    const foreign = await bridge.event('accept_user', 'other-owner', { input, event_id: 'forged' });
    assert.equal(foreign.ok, false);
    assert.equal(foreign.attempted, true);
    assert.equal(foreign.reason, 'http_403');
  });
