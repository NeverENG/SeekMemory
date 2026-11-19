import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = fileURLToPath(new URL('..', import.meta.url));
const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', ...options });
  assert.equal(result.status, 0, `${command} ${args.join(' ')}\n${result.stdout}\n${result.stderr}\n${result.error ?? ''}`);
  return result.stdout;
}

test('npm tarball installs into an isolated DSH profile with its documented tools', (t) => {
  const tmp = mkdtempSync(path.join(os.tmpdir(), 'seekmemory-dsh-package-'));
  t.after(() => rmSync(tmp, { recursive: true, force: true }));
  const npmEnv = { ...process.env, npm_config_cache: path.join(tmp, 'npm-cache') };

  const [packed] = JSON.parse(run(npm, [
    'pack', '--json', '--ignore-scripts', '--pack-destination', tmp,
  ], { cwd: root, env: npmEnv }));
  const archive = path.join(tmp, packed.filename);
  const staging = path.join(tmp, 'staging');
  run(npm, [
    'install', '--offline', '--ignore-scripts', '--no-audit', '--no-fund',
    '--no-package-lock', '--prefix', staging, archive,
  ], { env: npmEnv });

  const plugin = path.join(staging, 'node_modules', 'dsh-seekmemory');
  const license = readFileSync(path.join(plugin, 'LICENSE-MIT'), 'utf8');
  assert.equal(license, readFileSync(path.join(root, '..', '..', 'LICENSE-MIT'), 'utf8'));

  const home = path.join(tmp, 'home');
  const profile = path.join(home, 'profiles', 'web');
  mkdirSync(profile, { recursive: true });
  writeFileSync(path.join(profile, 'package.json'), JSON.stringify({
    name: 'isolated-profile', dependencies: {}, dsh: { profile: { bundles: [] } },
  }));
  const installer = path.join(plugin, 'tools', 'install-profile.mjs');
  run(process.execPath, [installer, '--profile', 'web', '--plugin', plugin,
    '--backup-dir', tmp, '--rollback-dir', tmp], { env: { ...process.env, DSH_HOME: home } });
  const config = JSON.parse(readFileSync(path.join(profile, 'package.json'), 'utf8'));
  assert.equal(config.dependencies['dsh-seekmemory'], `link:${plugin.replace(/\\/g, '/')}`);
  assert.deepEqual(config.dsh.profile.bundles, ['dsh-seekmemory']);
  const installed = statSync(path.join(profile, 'node_modules', 'dsh-seekmemory'));
  const target = statSync(plugin);
  assert.deepEqual([installed.dev, installed.ino], [target.dev, target.ino]);

  const dump = path.join(tmp, 'dump.yml');
  writeFileSync(dump, '- id: dsh-seekmemory\n  name: dsh-seekmemory\n');
  assert.match(run(process.execPath, [path.join(plugin, 'scripts', 'postinstall-check.mjs'),
    '--dump', dump]), /PASS/);
  assert.match(run(process.execPath, [path.join(plugin, 'scripts', 'check-installed.mjs'),
    '--dump', dump]), /PASS/);
  assert.match(run(npm, ['run', 'check:installed', '--prefix', plugin, '--', '--dump', dump],
    { env: npmEnv }), /PASS/);
});
