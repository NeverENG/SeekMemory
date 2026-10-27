/**
 * 插件入口。只做装配，业务在 kernel-client / host-dsh。
 *
 * 启动顺序是刻意设计的（对应"崩了也要能起来"）：
 *   1. 先建**文件日志**（同步写）—— 崩溃前最后一行必须落盘
 *   2. 归一化配置（绝不抛）
 *   3. 启动跳闸（safe-mode）：手动开关 → 安全模式 → 开机标记
 *   4. 只在前三步都通过时，才注册钩子
 *   5. 全部成功后 markOk()，清掉 pending 标记
 *
 * 任何一步失败都只**返回**，绝不 throw：插件树全加载或全不加载，
 * 抛出去等于让用户打不开软件（G13）。
 */

import { normalize } from './config.js';
import { KernelClient } from './kernel-client.js';
import { registerHostHooks } from './host-dsh.js';
import { startExtractLoop } from './extract-bridge.js';
import { createFileLogger, resolveLogDir, errBrief } from './logger.js';
import { evaluateBoot, markCrash, recoveryHint } from './safe-mode.js';
import path from 'node:path';

export const name = 'dsh-seekmemory';

/** 只声明真正用到的服务。缺 systemPrompt 时插件优雅缺席，而不是拖垮整棵树。 */
export const inject = ['systemPrompt'];

const VERSION = '0.0.1';
let exitHookInstalled = false;
/** 本次启动的跳闸句柄与内核客户端，供退出钩子写诊断。 */
let activeBoot = null;
let activeKernel = null;
/** 跳闸状态目录。运行期未捕获异常时用来同步写 crash.json。 */
let activeStateDir = '';
/** 本次进程是否观测到未捕获异常（= 非正常死亡）。 */
let crashedByUncaught = false;

/**
 * 退出诊断。
 *
 * 关键改变：**不再用退出码决定 pending**。旧实现"非零且有未捕获异常才保留 pending"
 * 有两个漏洞：① Windows 上强杀不触发 exit 事件，pending 必然遗留，下次启动误跳闸；
 * ② 正常失败（如 headless 没配模型 exit 1）和真崩溃无法区分。
 *
 * 现在职责拆开：
 *   - 启动阶段是否走完：由 apply 末尾的 markOk() 决定（pending 时间窗只有几十毫秒）
 *   - 运行期是否崩过：由 uncaughtExceptionMonitor 同步写 crash.json 决定
 *   - exit 钩子只写诊断日志，不改变任何状态
 */
function installExitDiagnostic(logger) {
  if (exitHookInstalled) return;
  exitHookInstalled = true;
  try {
    // uncaughtExceptionMonitor 只**通知**、不阻止崩溃（不同于 uncaughtException 会吞掉默认行为），
    // 正好用来标记"这次是非正常死亡"，且不改变宿主的退出语义。
    try {
      process.on('uncaughtExceptionMonitor', (err) => {
        crashedByUncaught = true;
        // 必须同步落盘：此刻进程通常已经在退出路径上，异步写没有机会完成。
        const written = markCrash(activeStateDir, { message: errBrief(err), stack: err?.stack });
        try {
          logger?.error?.(
            `未处理异常，进程将退出: ${errBrief(err)}` + (written ? '（已写 crash.json，下次启动会跳闸）' : '（crash.json 写入失败）'),
          );
        } catch {
          /* ignore */
        }
      });
    } catch {
      /* 没有该事件就退化为"只有启动期能跳闸" */
    }

    process.on('exit', (code) => {
      try {
        logger?.info?.(`process.exit code=${code} crashed=${crashedByUncaught}（宿主退出，不改动跳闸状态）`);
        if (activeKernel?.summary) logger?.info?.(`内核统计: ${JSON.stringify(activeKernel.summary())}`);
        logger?.info?.(
          crashedByUncaught
            ? '本次有未捕获异常：crash.json 已保留，下次启动会计数并可能跳闸'
            : '本次无未捕获异常：跳闸状态保持 apply 结束时写入的值',
        );
      } catch {
        /* 退出路径绝不再抛 */
      }
    });
  } catch {
    /* ignore */
  }
}

function configSummary(cfg) {
  return [
    `enabled=${cfg.enabled}`,
    `contract=${cfg.hostContract}`,
    `budget=${cfg.budgetChars}`,
    `k=${cfg.k}`,
    `recallTimeout=${cfg.recallTimeoutMs}ms`,
    `subjectMode=${cfg.subjectMode}`,
    `runtime=${cfg.runtimePath ? 'explicit' : cfg.dataDir ? 'from-dataDir' : 'unset'}`,
    `injectRecall=${cfg.injectRecall}`,
    `injectPersona=${cfg.injectPersona}`,
  ].join(' ');
}

/**
 * @param {any} ctx cordis 上下文
 * @param {Record<string, unknown>} rawConfig 宿主传入的插件配置
 */
export function apply(ctx, rawConfig) {
  // ── 1. 先有日志，再谈别的 ───────────────────────────────
  // 关键：日志目录必须**在配置归一化之前**就定下来，否则"归一化之前的行"和
  // "之后的行"会落进两个文件——真崩时最后一行可能在不该看的那个里，等于白记。
  // 所以这里直接从原始配置里读 logDir（不改它、不校验它），保证全程同一个文件。
  let logger;
  try {
    const rawLogDir =
      rawConfig && typeof rawConfig === 'object' && typeof rawConfig.logDir === 'string' ? rawConfig.logDir : '';
    logger = createFileLogger({ dir: resolveLogDir(rawLogDir), mirror: ctx.logger, tag: 'boot' });
    installExitDiagnostic(logger);
    logger.info(`apply 开始 version=${VERSION} pid=${process.pid} node=${process.version} cwd=${process.cwd() ? 'set' : 'unset'}`);
    logger.info(
      `env: DISABLE=${process.env.SEEKMEMORY_DISABLE ?? '-'} FORCE=${process.env.SEEKMEMORY_FORCE ?? '-'} DSH_HOME=${process.env.DSH_HOME ? 'set' : '-'}`,
    );
    if (logger.file) logger.info(`日志文件: ${logger.file}`);
  } catch (err) {
    // 连日志都建不起来：只能靠宿主 logger，然后照常往下走
    try {
      ctx.logger?.warn?.(`[seekmemory] 文件日志初始化失败: ${errBrief(err)}`);
    } catch {
      /* ignore */
    }
  }

  // ── 2. 配置（绝不抛）───────────────────────────────────
  let cfg;
  try {
    const normalized = normalize(rawConfig);
    cfg = normalized.config;
    for (const w of normalized.warnings) logger?.warn?.(`配置: ${w}`);
  } catch (err) {
    logger?.error?.(`配置归一化失败，插件不启用: ${errBrief(err)}`);
    return;
  }

  if (!cfg.enabled) {
    logger?.info?.('配置 enabled=false，不注册任何钩子');
    return;
  }

  // ── 3. 启动跳闸 ────────────────────────────────────────
  let boot;
  try {
    const stateDir = cfg.stateDir || (logger?.file ? logger.file.replace(/[\\/][^\\/]+$/, '') : resolveLogDir(''));
    boot = evaluateBoot({
      stateDir,
      env: process.env,
      safeModeAfterFailures: cfg.safeModeAfterFailures,
      safeModeAutoRetry: cfg.safeModeAutoRetry,
      logger,
    });
    // 立刻记下状态目录：运行期任何时刻崩了，uncaughtExceptionMonitor 都要能写 crash.json
    if (boot.statePath) activeStateDir = path.dirname(boot.statePath);
    logger?.info?.(`跳闸结果: mode=${boot.mode} reason=${boot.reason}`);
  } catch (err) {
    // 跳闸模块自己崩了也不能拖垮宿主：按"正常启动"继续
    logger?.error?.(`启动跳闸判定异常（继续按正常模式）: ${errBrief(err)}`);
    boot = { mode: 'run', reason: 'trip-check-failed', markOk: () => {} };
  }

  if (boot.mode !== 'run') {
    logger?.warn?.(`不注册钩子（mode=${boot.mode}）。\n${recoveryHint(boot.statePath ?? '', logger?.file ?? '')}`);
    return;
  }

  // ── 4. 内核客户端 + 钩子 ───────────────────────────────
  logger?.info?.(`配置: ${configSummary(cfg)}`);

  let kernel;
  try {
    kernel = new KernelClient({ config: cfg, logger });
  } catch (err) {
    logger?.error?.(`内核客户端初始化失败，插件不启用: ${errBrief(err)}`);
    return;
  }

  void kernel
    .health()
    .then((r) => {
      if (!r.ok) logger?.warn?.(`内核未连接（${r.reason}），记忆降级为不注入；对话不受影响`);
      else logger?.info?.('内核健康检查通过');
    })
    .catch((err) => {
      // 未处理的 rejection 会直接杀进程，这里必须吞掉
      logger?.warn?.(`探活异常（已吞掉）: ${errBrief(err)}`);
    });

  let hooks;
  try {
    logger?.info?.('开始注册钩子');
    hooks = registerHostHooks({ ctx, config: cfg, kernel, logger });
    logger?.info?.(`钩子注册完成，共 ${hooks.disposers.length} 个 disposer`);

    // M5：拉取式抽取循环（默认关）。它自己不抢资源，空闲 60s 一次 plan。
    const extract = startExtractLoop({ ctx, config: cfg, kernel, logger });
    hooks.disposers.push(() => extract.stop());
  } catch (err) {
    logger?.error?.(`钩子注册失败，插件降级为不工作: ${errBrief(err)}`);
    logger?.error?.(`如反复失败，删除 boot.json 或设 SEEKMEMORY_DISABLE=1 可让宿主正常启动`);
    return; // **不 markOk**：下次启动会自动进安全模式
  }

  // ── 5. 卸载 ────────────────────────────────────────────
  try {
    ctx.effect(() => () => {
      logger?.info?.('开始卸载');
      for (const dispose of hooks.disposers.splice(0)) {
        try {
          dispose();
        } catch {
          /* agent 可能已先步销毁 */
        }
      }
      logger?.info?.('已卸载，钩子全部回收');
    });
  } catch (err) {
    logger?.warn?.(`生命周期注册失败（可能热重载残留）: ${errBrief(err)}`);
  }

  // ── 6. 启动阶段完成：立刻清 pending ────────────────────
  // pending 只代表"apply 走到这里之前没死"。之后再崩（运行期）由
  // uncaughtExceptionMonitor 写 crash.json 记录，不再依赖退出码/exit 事件。
  // 这样强杀（任务管理器、关窗口、断电）不会遗留 pending，也就不会误跳闸。
  activeBoot = boot;
  activeKernel = kernel;
  boot.markOk();
  logger?.info?.(
    `已就绪 version=${VERSION} contract=${cfg.hostContract}（启动阶段已确认；运行期未捕获异常会写 crash.json，下次启动跳闸）`,
  );
}
