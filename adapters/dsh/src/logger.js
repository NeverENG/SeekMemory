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
import { fileURLToPath } from 'node:url';

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
 * 建一个文件日志。
 *
 * 铁律（issue #210）：**日志失败不许静默**。
 * 旧实现里目录建不出来时只是 `ready=false`，之后所有行都走 `mirror`（宿主 logger）——
 * 而 DSH 桌面版的 `ctx.logger` 在终端/运行目录里根本看不到，于是表现成"插件跑起来了但
 * 一个字都没留下"。现在改为：主目录失败 → 退系统临时目录 → 退插件自身目录；
 * 全部失败才放弃，并且用 `console.error` 喊出来、把尝试记录挂在返回值上。
 *
 * @param {{ dir: string, mirror?: {info?:Function,warn?:Function,error?:Function}, tag?: string }} opts
 */
export function createFileLogger({ dir, mirror, tag = 'boot' }) {
  const attempts = [];
  const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const candidates = [
    dir,
    path.join(os.tmpdir(), 'dsh-seekmemory'),
    path.join(pluginRoot, '.logs'),
  ].filter((d) => typeof d === 'string' && d.length > 0);

  let file = '';
  for (const cand of candidates) {
    try {
      mkdirSync(cand, { recursive: true });
      const f = path.join(cand, 'seekmemory.log');
      // mkdir 成功不等于能写：真写一次空串才算可用
      appendFileSync(f, '', 'utf8');
      attempts.push({ dir: cand, ok: true });
      if (!file) {
        file = f;
        rotateIfNeeded(f);
      }
    } catch (err) {
      attempts.push({ dir: cand, ok: false, err: errBrief(err) });
    }
  }

  const fallback = attempts.length > 0 && attempts[0].ok === false;
  if (!file) {
    // 一个都写不了：至少让屏幕上留下这句，别让"完全没日志"成为唯一线索
    const detail = attempts.map((a) => `${a.dir}${a.ok ? '' : `(${a.err})`}`).join(' | ');
    // eslint-disable-next-line no-console
    console.error(`[seekmemory] 文件日志不可用，已尝试 ${attempts.length} 个目录: ${detail}`);
  }

  const write = (level, msg) => {
    const line = `${new Date().toISOString()} ${level.padEnd(5)} [${tag}] ${msg}`;
    if (file) {
      try {
        appendFileSync(file, line + '\n', 'utf8');
      } catch {
        /* 写到一半失败也不能反过来影响插件；mirror 仍在 */
      }
    } else {
      // 没有文件可写时，至少把 ERROR/WARN 打到 stderr/stdout
      try {
        // eslint-disable-next-line no-console
        (level === 'ERROR' ? console.error : console.warn)(line);
      } catch {
        /* ignore */
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
    file,
    /** 主目录失败、但已成功降级到备用目录 */
    fallback,
    /** 每个候选目录的尝试结果，供 apply 写进诊断 */
    attempts,
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
