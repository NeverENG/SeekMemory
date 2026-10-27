/**
 * 启动跳闸（safe mode）与崩溃信号。
 *
 * 要解决的问题：插件把宿主搞崩之后，**下一次启动必须还能起来**；
 * 同时**不能把"用户正常关进程"误判成崩溃**——误判的代价是插件永久消失。
 *
 * 两个独立信号，各管一段：
 *   boot.json   pending    → "启动阶段没走完"（apply 开始写，apply 结束立刻清）
 *   crash.json  runtime    → "运行期出现过未捕获异常"（uncaughtExceptionMonitor 同步落盘）
 *
 * 判定顺序（见 evaluateBoot）：
 *   手动禁用 → 显式 FORCE → 已在安全模式（可自愈重试）→ 运行期崩溃 →
 *   启动阶段遗留（连续多次才跳闸，单次且曾成功过判为强杀）→ 正常
 *
 * 为什么 pending 只在启动阶段有效：
 *   旧实现把 pending 留到进程退出才清，结果 Windows 上任务管理器结束、关窗口、
 *   断电（都不触发 exit 事件）都会遗留 pending，下次启动被当成崩溃。
 *   现在 pending 的时间窗只有 apply 的几十毫秒，强杀撞进来的概率极低；
 *   运行期崩溃改由 crash.json 显式记录，不依赖退出码、也不依赖 exit 事件。
 *
 * 已知盲区（无法在本模块内解决）：崩溃发生在**模块导入期**时 apply 还没跑，
 * 标记写不下去。那属于"代码/文件坏了"，只能靠发布前的真机 import 冒烟 +
 * dump-config 检查发现，不做运行时兜底（动态 import 会改变钩子注册时序）。
 */

import { readFileSync, writeFileSync, renameSync, mkdirSync, existsSync, rmSync } from 'node:fs';
import path from 'node:path';

export const DISABLE_ENV = 'SEEKMEMORY_DISABLE';
export const FORCE_ENV = 'SEEKMEMORY_FORCE';
export const STATE_FILE = 'boot.json';
export const CRASH_FILE = 'crash.json';

/** 连续几次"启动阶段没走完"才判崩溃。1 = 一次就跳闸。 */
const DEFAULT_SAFE_AFTER = 1;
/** 判定"单次遗留 = 强杀"用：曾经成功过，且连续遗留次数低于这个值。 */
const INTERRUPTED_TOLERANCE = 3;
/** 安全模式里连续启动几次后自动重试一次。0 = 永不自动重试。 */
const DEFAULT_AUTO_RETRY = 3;

function readJson(file) {
  try {
    return JSON.parse(readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}

function writeJson(file, value) {
  const tmp = `${file}.tmp-${process.pid}`;
  writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf8');
  renameSync(tmp, file); // 原子写：崩在中间也不会留下半个文件
}

function bootPath(stateDir) {
  return path.join(stateDir, STATE_FILE);
}

function crashPath(stateDir) {
  return path.join(stateDir, CRASH_FILE);
}

/**
 * 运行期未捕获异常时调用。必须**同步**写完：调用时进程通常已经在退出路上，
 * 异步写没有机会落盘。返回值只用于日志，不改变宿主行为。
 *
 * @param {string} stateDir
 * @param {{ message?: string, stack?: string }} info
 * @returns {boolean} 是否真的写下去了
 */
export function markCrash(stateDir, info = {}) {
  if (!stateDir) return false;
  try {
    mkdirSync(stateDir, { recursive: true });
    writeJson(crashPath(stateDir), {
      at: new Date().toISOString(),
      pid: process.pid,
      message: String(info.message ?? 'unknown').slice(0, 500),
      stack: String(info.stack ?? '').slice(0, 2000),
    });
    return true;
  } catch {
    return false;
  }
}

export function readCrash(stateDir) {
  return stateDir ? readJson(crashPath(stateDir)) : null;
}

export function clearCrash(stateDir) {
  if (!stateDir) return;
  try {
    rmSync(crashPath(stateDir), { force: true });
  } catch {
    /* ignore */
  }
}

export function stateExists(stateDir) {
  return existsSync(bootPath(stateDir));
}

/**
 * @param {{
 *   stateDir: string,
 *   env?: Record<string,string|undefined>,
 *   safeModeAfterFailures?: number,
 *   safeModeAutoRetry?: number,
 *   logger: any
 * }} opts
 * @returns {{
 *   mode: 'run'|'safe'|'disabled',
 *   reason: string,
 *   statePath: string,
 *   markOk: () => void,
 *   crash?: object|null
 * }}
 */
export function evaluateBoot({ stateDir, env = process.env, safeModeAfterFailures, safeModeAutoRetry, logger }) {
  const statePath = bootPath(stateDir);
  const noop = () => {};

  // 1. 手动总开关：优先级最高，且**不写状态**（免得手动禁用被记成一次崩溃）
  if (env[DISABLE_ENV] === '1') {
    logger?.warn?.(`${DISABLE_ENV}=1：插件按手动开关禁用，不注册任何钩子（未改动 boot.json）`);
    return { mode: 'disabled', reason: 'env', statePath, markOk: noop };
  }

  // 2. 状态目录不可写：无法跳闸，只能照常跑并说明
  try {
    mkdirSync(stateDir, { recursive: true });
  } catch (err) {
    logger?.warn?.(`状态目录不可写（${stateDir}），无法启用自动跳闸：${err?.message ?? err}`);
    return { mode: 'run', reason: 'no-state-dir', statePath, markOk: noop };
  }

  const prev = readJson(statePath);
  const crash = readCrash(stateDir);
  const safeAfter = clampInt(safeModeAfterFailures, 1, 10, DEFAULT_SAFE_AFTER);
  const autoRetry = clampInt(safeModeAutoRetry, 0, 50, DEFAULT_AUTO_RETRY);

  // 3. 显式解除安全模式
  if (env[FORCE_ENV] === '1') {
    logger?.warn?.(`${FORCE_ENV}=1：强制清除安全模式，重新尝试加载`);
    clearCrash(stateDir);
    try {
      writeJson(statePath, freshPending({ note: 'force' }));
    } catch {
      /* ignore */
    }
    return { mode: 'run', reason: 'force', statePath, markOk: () => markOk(statePath, logger) };
  }

  // 4. 已在安全模式：计数，够次数就自动重试一次（自愈），否则保持
  if (prev?.safeMode === true) {
    const launches = Number(prev.safeLaunches ?? 0) + 1;
    if (autoRetry > 0 && launches >= autoRetry) {
      logger?.warn?.(
        `安全模式已持续 ${launches} 次启动，自动重试一次（上次原因：${prev.reason ?? 'unknown'}）。` +
          `恢复：删除 ${statePath} 或设置 ${FORCE_ENV}=1`,
      );
      clearCrash(stateDir);
      try {
        writeJson(statePath, freshPending({ note: 'auto-retry-after-safe-mode' }));
      } catch {
        /* ignore */
      }
      return { mode: 'run', reason: 'auto-retry', statePath, markOk: () => markOk(statePath, logger) };
    }
    try {
      writeJson(statePath, { ...prev, safeLaunches: launches });
    } catch {
      /* ignore */
    }
    logger?.error?.(
      `处于安全模式（上次原因：${prev.reason ?? 'unknown'}，自 ${prev.safeSince ?? '?'}）。` +
        `插件不工作，但宿主可正常启动。已连续 ${launches}/${autoRetry || '∞'} 次；` +
        `恢复：删除 ${statePath} 或设置 ${FORCE_ENV}=1`,
    );
    return { mode: 'safe', reason: String(prev.reason ?? 'safe-mode'), statePath, markOk: noop, crash };
  }

  // 5. 运行期崩过（uncaughtExceptionMonitor 留下的信号）→ 跳闸
  if (crash) {
    const state = {
      pending: false,
      attempts: 0,
      safeMode: true,
      safeLaunches: 0,
      reason: 'runtime-crash',
      crashAt: crash.at ?? null,
      crashMessage: crash.message ?? '',
      safeSince: new Date().toISOString(),
      lastStartAt: prev?.lastStartAt ?? null,
      lastOkAt: prev?.lastOkAt ?? null,
    };
    try {
      writeJson(statePath, state);
    } catch {
      /* ignore */
    }
    clearCrash(stateDir);
    logger?.error?.(
      `检测到上次运行期有未捕获异常（${crash.at ?? '?'}：${crash.message ?? 'unknown'}），已进入**安全模式**：不注册任何钩子。` +
        `宿主现在可以正常启动。恢复：① 看 seekmemory.log 定位崩点；② 删除 ${statePath} 或设置 ${FORCE_ENV}=1 后重启`,
    );
    return { mode: 'safe', reason: state.reason, statePath, markOk: noop, crash };
  }

  // 6. 启动阶段遗留（apply 没走完）
  const interrupted = prev?.pending === true;
  if (interrupted) {
    const attempts = Number(prev?.attempts ?? 1) + 1;
    const lasted = prev?.lastOkAt ? '曾经成功启动过' : '从未成功启动过';
    const tolerated = prev?.lastOkAt && attempts < INTERRUPTED_TOLERANCE;

    // 单次遗留 + 历史上成功过 → 判定为"启动中被强杀"，不跳闸
    if (tolerated) {
      logger?.warn?.(
        `上次启动在启动阶段被中断（attempts=${attempts}，${lasted}），判定为进程被强杀而非插件崩溃；` +
          `本次照常加载。连续 ${INTERRUPTED_TOLERANCE} 次遗留才会跳闸。`,
      );
      try {
        writeJson(statePath, freshPending({ note: 'recovered-from-interrupted-boot' }));
      } catch {
        /* ignore */
      }
      return { mode: 'run', reason: 'recovered-interrupted', statePath, markOk: () => markOk(statePath, logger) };
    }

    if (attempts >= safeAfter) {
      const state = {
        pending: false,
        attempts,
        safeMode: true,
        safeLaunches: 0,
        reason: 'startup-did-not-complete',
        safeSince: new Date().toISOString(),
        lastStartAt: prev?.lastStartAt ?? null,
        lastOkAt: prev?.lastOkAt ?? null,
      };
      try {
        writeJson(statePath, state);
      } catch {
        /* ignore */
      }
      logger?.error?.(
        `检测到上次启动未完成（attempts=${attempts}，${lasted}），已进入**安全模式**：不注册任何钩子。` +
          `宿主现在可以正常启动。恢复步骤：① 先看 seekmemory.log 最后几行定位崩点；② 删除 ${statePath} 或设置 ${FORCE_ENV}=1 后重启`,
      );
      return { mode: 'safe', reason: state.reason, statePath, markOk: noop };
    }
  }

  // 7. 正常启动：先落 pending 标记，再干活；apply 结束会立刻清掉
  const attempts = interrupted ? Number(prev?.attempts ?? 1) + 1 : 1;
  try {
    writeJson(statePath, freshPending({ attempts, note: interrupted ? 'retry-after-incomplete-boot' : 'boot' }));
  } catch (err) {
    logger?.warn?.(`写 boot.json 失败（跳闸失效，但仍继续）：${err?.message ?? err}`);
  }

  return {
    mode: 'run',
    reason: interrupted ? 'retry' : 'fresh',
    statePath,
    markOk: () => markOk(statePath, logger),
  };
}

function freshPending({ attempts = 1, note = 'boot' } = {}) {
  return {
    pending: true,
    attempts,
    lastStartAt: new Date().toISOString(),
    lastOkAt: null,
    safeMode: false,
    note,
  };
}

function clampInt(value, min, max, fallback) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(n)));
}

/** 启动阶段走完就调用：清 pending，留下 lastOkAt 供下次判断"曾经成功过"。 */
export function markOk(statePath, logger) {
  try {
    writeJson(statePath, {
      pending: false,
      attempts: 0,
      lastOkAt: new Date().toISOString(),
      safeMode: false,
    });
    logger?.info?.('启动阶段完成标记已写入（boot.json pending=false）');
  } catch (err) {
    logger?.warn?.(`写启动完成标记失败：${err?.message ?? err}`);
  }
}

/** 给出人可读的恢复说明，写进日志与错误信息。logPath 由调用方传入实际日志路径。 */
export function recoveryHint(statePath, logPath = '') {
  const log = logPath || (statePath ? path.join(path.dirname(statePath), 'seekmemory.log') : '(见插件配置 logDir)');
  return [
    `恢复三步：`,
    `  1) 看日志最后几行：${log}`,
    `  2) 删除 ${statePath}（或设 ${FORCE_ENV}=1）`,
    `  3) 重启 DSH`,
    `彻查禁用：设置 ${DISABLE_ENV}=1 启动一次，插件完全不加载。`,
  ].join('\n');
}
