/**
 * 文件日志：同步写，崩之前一定能落盘。
 *
 * 为什么不用 ctx.logger 就够：DSH 崩溃时宿主自己的日志缓冲区可能还没刷，
 * 而我们要的正是"崩之前最后一句是什么"。appendFileSync 每次落盘，代价可接受
 * （一次启动只有十几行）。
 *
 * 纪律（对齐上游 INVARIANTS）：**日志不含消息正文、提示词、凭据、会话标识**。
 * 需要记录内容时只记长度与哈希前几位。
 */

import { appendFileSync, mkdirSync, renameSync, statSync } from 'node:fs';
import path from 'node:path';
import os from 'node:os';

const MAX_BYTES = 2 * 1024 * 1024; // 2MB 后轮转一份 .1，避免无限长

/** 解析日志目录：显式配置 > DSH_HOME > 系统临时目录。 */
export function resolveLogDir(configured) {
  if (configured) return configured;
  const home = process.env.DSH_HOME;
  if (home) return path.join(home, 'seekmemory-logs');
  return path.join(os.tmpdir(), 'dsh-seekmemory');
}

function rotateIfNeeded(file) {
  try {
    const st = statSync(file);
    if (st.size > MAX_BYTES) renameSync(file, `${file}.1`);
  } catch {
    /* 文件不存在就算了 */
  }
}

/**
 * @param {{ dir: string, mirror?: {info?:Function,warn?:Function,error?:Function}, tag?: string }} opts
 */
export function createFileLogger({ dir, mirror, tag = 'boot' }) {
  let ready = false;
  try {
    mkdirSync(dir, { recursive: true });
    ready = true;
  } catch {
    ready = false; // 日志目录不可写不能反过来影响插件
  }
  const file = path.join(dir, 'seekmemory.log');
  if (ready) rotateIfNeeded(file);

  const write = (level, msg) => {
    const line = `${new Date().toISOString()} ${level.padEnd(5)} [${tag}] ${msg}`;
    if (ready) {
      try {
        appendFileSync(file, line + '\n', 'utf8');
      } catch {
        /* 写不进去就只走宿主日志 */
      }
    }
    try {
      if (level === 'ERROR') mirror?.error?.(`[seekmemory] ${msg}`);
      else if (level === 'WARN') mirror?.warn?.(`[seekmemory] ${msg}`);
      else mirror?.info?.(`[seekmemory] ${msg}`);
    } catch {
      /* 宿主日志失败无关紧要 */
    }
  };

  return {
    file: ready ? file : '',
    info: (m) => write('INFO', m),
    warn: (m) => write('WARN', m),
    error: (m) => write('ERROR', m),
    /** 带子标签的日志器，用来标记阶段。 */
    withTag(t) {
      const inner = (level, msg) => write(level, msg);
      return {
        info: (m) => inner('INFO', m),
        warn: (m) => inner('WARN', m),
        error: (m) => inner('ERROR', m),
      };
    },
  };
}

/** 只保留异常的类型与首行，避免把正文/路径带进日志。 */
export function errBrief(err) {
  if (!err) return 'unknown';
  const name = err.name ?? 'Error';
  const msg = String(err.message ?? err);
  return `${name}: ${msg.slice(0, 200)}`;
}
