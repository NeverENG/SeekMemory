import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as pause } from 'node:timers/promises';
import test from 'node:test';
import { KernelClient } from '../src/kernel-client.js';
import { runOnce } from '../src/extract-bridge.js';

const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const cli = fileURLToPath(new URL('../../../scripts/serve.py', import.meta.url));

// Fake only the host's paid model, not the adapter, HTTP transport or Python kernel.
test('DSH extraction bridge captures, commits and recalls through real Python loopback',
  { timeout: 15_000 }, async (t) => {
    const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-dsh-extract-'));
    const child = spawn(python, [cli, '--data-dir', dir, '--port', '0', '--quiet'], {
      stdio: 'ignore', windowsHide: true,
    });
    const exited = new Promise((resolve) => child.once('exit', resolve));
    t.after(async () => { child.kill(); await exited; rmSync(dir, { recursive: true, force: true }); });
    const runtimePath = path.join(dir, 'runtime.json');
    let endpoint;
    for (let i = 0; i < 150; i += 1) {
      try { endpoint = JSON.parse(readFileSync(runtimePath, 'utf8')); break; }
      catch { await pause(20); }
    }
    assert.equal(endpoint?.host_contract, 1);
    const logger = { info() {}, warn() {}, error() {} };
    const config = {
      runtimePath, hostContract: 1, logPrefix: '[test]', subjectKey: 'loopback:default',
      llmProvider: 'test', llmModel: 'deterministic', captureTimeoutMs: 3000,
      recallTimeoutMs: 3000, budgetChars: 600, k: 8,
    };
    const kernel = new KernelClient({ config, logger });
    assert.equal((await kernel.health()).ok, true);
    const captured = await kernel.capture({
      subject_key: config.subjectKey, role: 'user', speaker: 'local-user',
      text: '我周末要去医院检查眼睛', at: '2026-10-29T10:00:00',
      msg_id: 'extract-python-smoke',
    });
    assert.equal(captured.ok, true);
    const sourceId = captured.data.source_id;
    const otherHost = new KernelClient({ config: { ...config }, logger });
    assert.equal((await otherHost.plan(config.subjectKey)).ok, true);
    assert.equal((await otherHost.capture({ subject_key: 'other:user', text: 'foreign' })).ok, false);
    assert.equal((await otherHost.recall({ subjectKey: 'other:user', query: '医院' })).ok, false);
    assert.equal((await otherHost.persona('other:user')).ok, false);
    const answer = JSON.stringify([{
      level: 'fact', text: '用户周末要去医院检查眼睛', tags: '医院 检查 眼睛 周末',
      about: 'other', subject_kind: 'speaker', subject_id: 'user(local-user)',
      event_at: '2026-10-29T10:00:00', confidence: 0.95,
      arousal: 0.2, valence: 0, funny: 0, first: true,
      evidence_source_ids: [sourceId],
    }]);
    const ctx = { get(name) {
      if (name !== 'llm') return undefined;
      return { stream: async function* ({ messages }) {
        assert.match(JSON.stringify(messages), /医院/);
        yield { type: 'block-end', block: { type: 'text', text: answer } };
        yield { type: 'finish', reason: { kind: 'stop' } };
      } };
    } };
    const committed = await runOnce({ ctx, config, kernel, logger });
    assert.equal(committed.outcome, 'done', committed.detail);
    assert.equal(JSON.parse(committed.detail).written, 1, committed.detail);
    const recalled = await kernel.recall({ subjectKey: config.subjectKey, query: '医院 检查 眼睛' });
    assert.equal(recalled.ok, true);
    assert.equal((await otherHost.recall({ subjectKey: config.subjectKey, query: '医院 检查 眼睛' })).ok, true);
    assert.ok(recalled.data.items.length > 0, `recall must actually render an Artifact: chars=${recalled.data.chars} mode=${recalled.data.info?.mode} picked=${recalled.data.info?.picked} candidates=${recalled.data.info?.candidates} gate=${JSON.stringify(recalled.data.info?.gate)}`);
    const tinyBudget = new KernelClient({ config: { ...config, budgetChars: 1 }, logger });
    const limited = await tinyBudget.recall({ subjectKey: config.subjectKey, query: '医院 检查 眼睛' });
    assert.equal(limited.ok, true);
    assert.equal(limited.data.block, '', 'a tiny request budget must not inject memory');
    assert.equal((await kernel.plan(config.subjectKey)).data, null);
  });
