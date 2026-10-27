#!/usr/bin/env node
/**
 * M0 mock 内核：让适配器（M3）不等 Python 的 serve.py 就能开工。
 *
 * 它不是 SeekMemory 的替代实现，只是**契约的可执行样例**：
 * 端点、字段、超时语义、fail-open 行为都按《方案 v2.1》§4.1 走，
 * 数据是内存里的几条假记忆。
 *
 * 用法：
 *   node mock/kernel.mjs --data-dir <dir> [--port 0] [--token <t>]
 *   输出：<data-dir>/runtime.json  { port, token, pid, version, host_contract, started_at }
 *
 * 环境变量（用于故障注入，验 fail-open）：
 *   MOCK_DELAY_MS=5000   /recall 延迟
 *   MOCK_FAIL=500        /recall 返回 500
 *   MOCK_EMPTY=1         /recall 返回空块
 *   MOCK_BAD_CONTRACT=9  /healthz 报一个不同的 host_contract
 */

import { createServer } from 'node:http';
import { randomBytes, randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync, renameSync } from 'node:fs';
import path from 'node:path';

const VERSION = '0.0.1-mock';
const HOST_CONTRACT = 1;

// ---------- 参数 ----------
function parseArgs(argv) {
  const out = { dataDir: '', port: 0, token: '' };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--data-dir') out.dataDir = argv[++i] ?? '';
    else if (a === '--port') out.port = Number(argv[++i] ?? 0);
    else if (a === '--token') out.token = argv[++i] ?? '';
  }
  if (!out.dataDir) {
    console.error('mock: --data-dir is required');
    process.exit(2);
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const token = args.token || randomBytes(24).toString('hex');
const dataDir = path.resolve(args.dataDir);
mkdirSync(dataDir, { recursive: true });

// ---------- 假数据 ----------
const state = {
  sources: [],
  memories: [
    {
      id: 'mem_1',
      level: 'fact',
      subject: 'test:user:1',
      text: '他的键盘是 Akko 机械键盘，经常出现偶发大延迟',
      tags: '键盘 延迟 硬件',
      evidence: ['src_seed_1'],
      sensitivity: 'normal',
    },
    {
      id: 'mem_2',
      level: 'scene',
      subject: 'test:user:1',
      text: '上周三排查键盘延迟，最后怀疑是 USB 仲裁服务',
      tags: '排查 键盘 USB',
      evidence: ['src_seed_2'],
      sensitivity: 'normal',
    },
    {
      id: 'mem_3',
      level: 'fact',
      subject: 'test:user:1',
      text: '这条是 secret，任何情况下都不许召回',
      tags: '秘密',
      evidence: ['src_seed_3'],
      sensitivity: 'secret',
    },
  ],
  stats: { captures: 0, recalls: 0, plans: 0, commits: 0 },
};

// ---------- 工具 ----------
function bigrams(text) {
  const s = String(text ?? '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
  const out = new Set();
  for (let i = 0; i < Math.max(0, s.length - 1); i += 1) out.add(s.slice(i, i + 2));
  return out;
}

function score(query, mem) {
  const q = bigrams(query);
  if (q.size === 0) return 0;
  const doc = bigrams(`${mem.text} ${mem.tags}`);
  let hit = 0;
  for (const g of q) if (doc.has(g)) hit += 1;
  return hit / q.size;
}

function recallBlock(items, budgetChars) {
  if (items.length === 0) return '';
  const lines = [];
  let used = 0;
  const head = '<relevant-memories>\n以下是当前对话召回的相关记忆，仅供参考：\n';
  const tail = '\n</relevant-memories>';
  const room = Math.max(0, budgetChars - head.length - tail.length);
  for (const it of items) {
    const line = `- [${it.level}] ${it.text}`;
    if (used + line.length + 1 > room) break;
    lines.push(line);
    used += line.length + 1;
  }
  if (lines.length === 0) return '';
  return `${head}${lines.join('\n')}${tail}`;
}

function json(res, code, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(code, { 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > 1_000_000) reject(new Error('body too large'));
      else chunks.push(c);
    });
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      if (!raw) return resolve({});
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        reject(new Error(`bad json: ${err.message}`));
      }
    });
    req.on('error', reject);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 路由 ----------
const server = createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  const route = `${req.method} ${url.pathname}`;

  // 鉴权：除 healthz 外都要 Bearer token
  if (url.pathname !== '/healthz') {
    const auth = req.headers.authorization ?? '';
    if (auth !== `Bearer ${token}`) {
      return json(res, 401, { error: 'unauthorized' });
    }
  }

  try {
    if (route === 'GET /healthz') {
      const hc = Number(process.env.MOCK_BAD_CONTRACT ?? HOST_CONTRACT);
      return json(res, 200, {
        ok: true,
        version: VERSION,
        host_contract: hc,
        db: path.join(dataDir, 'mock.db'),
        uptime_s: Math.round(process.uptime()),
      });
    }

    if (route === 'POST /capture') {
      const body = await readBody(req);
      state.stats.captures += 1;
      const source = {
        source_id: `src_${randomUUID().slice(0, 8)}`,
        subject_key: body.subject_key ?? '',
        session: body.session ?? '',
        role: body.role ?? 'user',
        text: String(body.text ?? ''),
        at: body.at ?? new Date().toISOString(),
        msg_id: body.msg_id ?? '',
      };
      state.sources.push(source);
      return json(res, 200, { accepted: true, source_id: source.source_id });
    }

    if (route === 'POST /recall') {
      if (process.env.MOCK_FAIL) {
        await sleep(Number(process.env.MOCK_DELAY_MS ?? 50));
        return json(res, Number(process.env.MOCK_FAIL), { error: 'mock failure' });
      }
      if (process.env.MOCK_DELAY_MS) await sleep(Number(process.env.MOCK_DELAY_MS));
      const body = await readBody(req);
      state.stats.recalls += 1;
      const budget = Math.max(0, Number(body.budget_chars ?? 600));
      const k = Math.max(0, Math.min(50, Number(body.k ?? 8)));
      const query = String(body.query ?? '');
      const subject = body.subject_key ?? '';

      const candidates = state.memories
        .filter((m) => m.sensitivity !== 'secret') // 硬闸：secret 永不进候选池
        .filter((m) => !subject || m.subject === subject)
        .map((m) => ({ ...m, score: score(query, m) }))
        .filter((m) => m.score > 0)
        .sort((a, b) => b.score - a.score)
        .slice(0, k);

      const items = process.env.MOCK_EMPTY
        ? []
        : candidates.map((m) => ({
            id: m.id,
            level: m.level,
            text: m.text,
            score: Number(m.score.toFixed(3)),
            evidence: m.evidence,
          }));

      const block = process.env.MOCK_EMPTY ? '' : recallBlock(items, budget);
      return json(res, 200, {
        block,
        items,
        suppressed: candidates.length - items.length,
        took_ms: 1,
      });
    }

    if (route === 'GET /persona') {
      return json(res, 200, {
        revision: 3,
        text: '<persona>\n（mock）测过一个反复排查键盘延迟的用户。\n</persona>',
        chars: 42,
      });
    }

    if (route === 'GET /status') {
      return json(res, 200, {
        host_contract: Number(process.env.MOCK_BAD_CONTRACT ?? HOST_CONTRACT),
        version: VERSION,
        capacity: { memories: state.memories.length, sources: state.sources.length },
        queue: { pending: 0, deferred: 0 },
        budget: { dream_max_calls: 12, dream_token_budget: 60000, used_today: 0 },
        progress: { phase: 'idle', done: 0, total: 0, detail: '', started_at: null },
        degraded_reason: null,
        stats: state.stats,
      });
    }

    if (route === 'GET /extract/plan') {
      state.stats.plans += 1;
      // 默认 204：没事干。MOCK_PLAN=1 时给一个假任务，供 M5 开发。
      if (process.env.MOCK_PLAN === '1') {
        return json(res, 200, {
          task_id: 'task_1',
          chat_request: {
            system_prompt: 'mock extractor',
            prompt: '请输出 JSON 数组',
            max_tokens: 800,
            temperature: 0,
          },
        });
      }
      res.writeHead(204);
      return res.end();
    }

    if (route === 'POST /extract/commit') {
      const body = await readBody(req);
      state.stats.commits += 1;
      const raw = String(body.chat_response?.text ?? '');
      let parsed = null;
      try {
        parsed = JSON.parse(raw);
      } catch {
        return json(res, 200, { written: 0, skipped: 0, reason: 'unparsable' });
      }
      const list = Array.isArray(parsed) ? parsed : [];
      return json(res, 200, { written: list.length, skipped: 0, reason: '' });
    }

    return json(res, 404, { error: `no route ${route}` });
  } catch (err) {
    return json(res, 500, { error: err instanceof Error ? err.message : String(err) });
  }
});

// ---------- 启动 + runtime.json ----------
server.listen(args.port, '127.0.0.1', () => {
  const { port } = server.address();
  const runtime = {
    port,
    token,
    pid: process.pid,
    version: VERSION,
    host_contract: HOST_CONTRACT,
    started_at: new Date().toISOString(),
    db_path: path.join(dataDir, 'mock.db'),
  };
  const target = path.join(dataDir, 'runtime.json');
  const tmp = `${target}.tmp`;
  writeFileSync(tmp, JSON.stringify(runtime, null, 2), { encoding: 'utf8' });
  renameSync(tmp, target); // 原子写：适配器永远读不到半个文件
  console.log(`mock kernel listening on 127.0.0.1:${port}`);
  console.log(`runtime file: ${target}`);
});

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, () => {
    server.close(() => process.exit(0));
  });
}
