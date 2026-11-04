import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as pause } from 'node:timers/promises';
import test from 'node:test';

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
