/**
 * 契约客户端：只跟 loopback HTTP 说话，**永不抛异常**。
 *
 * 每个方法都返回 { ok, data?, reason? }。fail-open 的语义在这里落地：
 * 上层的每一次调用都不需要 try/catch，只看 ok。
 *
 * 降级原因是**枚举值**而不是布尔（《方案 v2.1》G14）：
 *   not_configured | no_runtime_file | bad_runtime_file | kernel_down
 *   timeout | http_401 | http_5xx | bad_json | contract_mismatch | exception
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';

const CACHE_MS = 1000;

export class KernelClient {
  #cfg;
  #logger;
  #cached = null;
  #cachedAt = 0;
  #degraded = null;
  /** 最近一次端点解析失败的原因，供 #call 归类，避免重复读文件误判。 */
  #lastResolveReason = '';
  /** 各降级原因累计次数：单槽状态会被一次成功抹掉，计数不会。 */
  #counters = Object.create(null);

  constructor({ config, logger }) {
    this.#cfg = config;
    this.#logger = logger;
  }

  /** @returns {{reason:string, detail:string, at:string}|null} */
  get degraded() {
    return this.#degraded;
  }

  #mark(reason, detail) {
    this.#degraded = { reason, detail: String(detail ?? ''), at: new Date().toISOString() };
    this.#counters[reason] = (this.#counters[reason] ?? 0) + 1;
    return { ok: false, reason, detail: this.#degraded.detail };
  }

  #clear() {
    this.#degraded = null;
  }

  /** 降级原因的中文说明，给状态面板/日志用。 */
  describeDegraded() {
    if (!this.#degraded) return '';
    const map = {
      not_configured: '未配置内核路径',
      no_runtime_file: '找不到 runtime.json（内核没起来）',
      bad_runtime_file: 'runtime.json 读不懂（可能正在写）',
      kernel_down: '内核不可达',
      timeout: '内核超时',
      bad_json: '内核返回非 JSON',
      contract_mismatch: '契约版本不匹配',
      exception: '未知异常',
    };
    const base = map[this.#degraded.reason] ?? this.#degraded.reason;
    return this.#degraded.detail ? `${base}：${this.#degraded.detail}` : base;
  }

  /**
   * 诊断摘要。单槽 `degraded` 会被一次成功清空，但 counters 不会——
   * "记忆其实一条都没记住"这种故障只能靠计数看出来。
   * 调用方：index.js 在卸载时写日志；宿主若要展示状态可读它。
   */
  summary() {
    return {
      reachable: this.#degraded === null,
      degraded: this.#degraded,
      describe: this.describeDegraded(),
      counters: { ...this.#counters },
    };
  }

  #runtimePath() {
    if (this.#cfg.runtimePath) return this.#cfg.runtimePath;
    if (this.#cfg.dataDir) return path.join(this.#cfg.dataDir, 'runtime.json');
    return '';
  }

  async #endpoint(force = false) {
    const now = Date.now();
    if (!force && this.#cached && now - this.#cachedAt < CACHE_MS) return this.#cached;

    const file = this.#runtimePath();
    if (!file) {
      this.#cached = null;
      this.#lastResolveReason = 'no_path';
      return null;
    }
    try {
      const raw = await readFile(file, 'utf8');
      const parsed = JSON.parse(raw);
      // 端口必须是合法整数：以前只校验 typeof === 'number'，99999 能过，
      // 随后 new URL() 在 try 外抛 TypeError，直接把宿主进程带走。
      // （真实崩溃，见 review-dsh-seekmemory.md 阻断项）
      const port = Number(parsed?.port);
      if (!parsed || !Number.isInteger(port) || port < 1 || port > 65535 || typeof parsed.token !== 'string') {
        this.#cached = null;
        this.#lastResolveReason = 'bad_runtime_file';
        return null;
      }
      this.#cached = {
        port,
        token: parsed.token,
        hostContract: Number(parsed.host_contract ?? 0),
        version: String(parsed.version ?? ''),
      };
      this.#cachedAt = now;
      this.#lastResolveReason = '';
      return this.#cached;
    } catch (err) {
      this.#cached = null;
      this.#lastResolveReason = err?.code === 'ENOENT' ? 'no_runtime_file' : 'bad_runtime_file';
      return null;
    }
  }

  async #call(pathname, { method = 'GET', body, timeoutMs, query } = {}) {
    const ep = await this.#endpoint();
    if (!ep) {
      // 用 #endpoint 记下的原因，不再重复读文件（重复读会导致误判成 kernel_down）
      const reason = this.#lastResolveReason;
      if (reason === 'no_path') return this.#mark('not_configured', pathname);
      if (reason === 'bad_runtime_file') return this.#mark('bad_runtime_file', pathname);
      return this.#mark('no_runtime_file', pathname);
    }

    const ms = timeoutMs ?? this.#cfg.recallTimeoutMs;
    // URL 构造必须在 try 内：它也会抛（端口非法、pathname 非法）
    let url;
    try {
      url = new URL(`http://127.0.0.1:${ep.port}${pathname}`);
      if (query) {
        for (const [k, v] of Object.entries(query)) {
          if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
        }
      }
    } catch (err) {
      return this.#mark('bad_endpoint', `${pathname}: ${err?.message ?? err}`);
    }

    try {
      const res = await fetch(url, {
        method,
        headers: {
          authorization: `Bearer ${ep.token}`,
          ...(body === undefined ? {} : { 'content-type': 'application/json' }),
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: AbortSignal.timeout(ms),
      });

      if (res.status === 204) {
        this.#clear();
        return { ok: true, data: null };
      }
      if (res.status === 401) return this.#mark('http_401', pathname);
      if (!res.ok) return this.#mark(`http_${res.status}`, pathname);

      let data;
      try {
        data = await res.json();
      } catch {
        return this.#mark('bad_json', pathname);
      }
      this.#clear();
      return { ok: true, data };
    } catch (err) {
      const name = err?.name ?? '';
      if (name === 'TimeoutError' || name === 'AbortError') return this.#mark('timeout', `${pathname} > ${ms}ms`);
      // 连接被拒 = 内核没起来，是最常见的一种
      this.#cached = null;
      return this.#mark('kernel_down', `${pathname}: ${err?.message ?? String(err)}`);
    }
  }

  // ---------- 契约端点 ----------

  async health() {
    const r = await this.#call('/healthz', { timeoutMs: 1000 });
    if (!r.ok) return r;
    const got = Number(r.data?.host_contract ?? 0);
    if (got !== this.#cfg.hostContract) {
      return this.#mark('contract_mismatch', `kernel=${got} adapter=${this.#cfg.hostContract}`);
    }
    this.#logger?.info?.(
      `${this.#cfg.logPrefix} 内核已连接 v${r.data?.version ?? '?'} contract=${got}`,
    );
    return r;
  }

  capture(payload) {
    return this.#call('/capture', { method: 'POST', body: payload, timeoutMs: this.#cfg.captureTimeoutMs });
  }

  recall({ query, subjectKey }) {
    return this.#call('/recall', {
      method: 'POST',
      body: {
        subject_key: subjectKey,
        query,
        budget_chars: this.#cfg.budgetChars,
        k: this.#cfg.k,
        now: new Date().toISOString(),
      },
      timeoutMs: this.#cfg.recallTimeoutMs,
    });
  }

  persona(subjectKey) {
    return this.#call('/persona', { query: { subject_key: subjectKey }, timeoutMs: 1000 });
  }

  status() {
    return this.#call('/status', { timeoutMs: 2000 });
  }

  /** 拉取式抽取：204 = 没事干。 */
  plan(subjectKey) {
    return this.#call('/extract/plan', { query: { subject_key: subjectKey }, timeoutMs: 26_000 });
  }

  commit({ taskId, chatResponse }) {
    return this.#call('/extract/commit', {
      method: 'POST',
      body: { task_id: taskId, chat_response: chatResponse },
      timeoutMs: 3000,
    });
  }
}
