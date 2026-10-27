/**
 * M5：抽取归宿主（拉取式）。
 *
 * 契约（方案 v2.1 §4.3）：
 *   插件 GET /extract/plan → 内核返回 {task_id, chat_request}
 *   插件用**宿主的** LLM 执行 → POST /extract/commit {task_id, chat_response}
 *
 * 为什么是这个方向：内核不持密钥、不反向开端口、不在事务里发网络请求；
 * 凭据与用量记账全留在宿主。
 *
 * 宿主 LLM 调用面（读自 dsh-prime-memory/dist/llm.js:415-464，非猜测）：
 *   ctx.llm.stream({provider, model, system, messages, temperature, maxTokens, signal})
 *   for await → chunk.type: 'text-delta' | 'block-end' | 'usage' | 'finish'
 *   正文只取 block-end 的 block.text；text-delta 仅在缺 block-end 时兜底（都累计会翻倍）
 */

import { buildUserMessage } from './message.js';
import { errBrief } from './logger.js';

const IDLE_MS = 60_000;
const MAX_BACKOFF_MS = 10 * 60_000;

/** 从宿主 llm 服务的流里取文本，语义照抄上游：block-end 权威，delta 兜底。 */
async function chatViaHost(ctx, { provider, model, system, user, maxTokens, temperature, logger }) {
  const llm = ctx.get?.('llm') ?? ctx.llm;
  if (!llm || typeof llm.stream !== 'function') {
    return { ok: false, reason: 'no_llm_service' };
  }
  let message;
  try {
    message = await buildUserMessage({
      text: user,
      kind: 'plugin:seekmemory',
      form: 'extract',
      logger,
      envelope: false,
    });
  } catch (err) {
    return { ok: false, reason: 'no_message_factory', detail: errBrief(err) };
  }

  let blockText = '';
  let deltaText = '';
  let usage = null;
  try {
    const stream = llm.stream({
      provider,
      model,
      system,
      messages: [message],
      temperature: temperature ?? 0,
      maxTokens: maxTokens ?? 800,
      signal: AbortSignal.timeout(120_000),
    });
    for await (const chunk of stream) {
      if (chunk?.type === 'block-end' && chunk.block?.type === 'text') blockText += chunk.block.text;
      else if (chunk?.type === 'text-delta') deltaText += chunk.text ?? '';
      else if (chunk?.type === 'usage') usage = chunk.usage ?? null;
      else if (chunk?.type === 'finish' && (chunk.reason?.kind === 'error' || chunk.reason?.kind === 'aborted')) {
        return { ok: false, reason: 'llm_finish_' + chunk.reason.kind, detail: chunk.reason?.failure?.message ?? '' };
      }
    }
  } catch (err) {
    return { ok: false, reason: 'llm_throw', detail: errBrief(err) };
  }

  const text = blockText || deltaText;
  if (!text.trim()) return { ok: false, reason: 'llm_empty' };
  return {
    ok: true,
    text,
    usage_in: Number(usage?.inputTokens ?? 0),
    usage_out: Number(usage?.outputTokens ?? 0),
  };
}

/**
 * 跑一次"取活 → 执行 → 交回"。
 * @returns {Promise<{outcome:'idle'|'done'|'skipped'|'error', detail?:string}>}
 */
export async function runOnce({ ctx, config, kernel, logger }) {
  const planned = await kernel.plan(config.subjectKey || 'local:single:default');
  if (!planned.ok) {
    // 内核不可达是常态（用户没起内核），按 idle 处理并交给退避
    return { outcome: 'error', detail: planned.reason };
  }
  if (!planned.data) return { outcome: 'idle' }; // 204：没事干

  const task = planned.data;
  const req = task.chat_request ?? {};
  const taskId = String(task.task_id ?? '');
  if (!taskId || !req.prompt) return { outcome: 'skipped', detail: 'task 缺 task_id 或 prompt' };

  if (!config.llmProvider || !config.llmModel) {
    // 不猜宿主的默认模型：没配就明确说，别静默丢弃任务
    return { outcome: 'skipped', detail: 'llmProvider/llmModel 未配置（内核任务保留，未提交）' };
  }

  const reply = await chatViaHost(ctx, {
    provider: config.llmProvider,
    model: config.llmModel,
    system: req.system_prompt ?? '',
    user: req.prompt,
    maxTokens: req.max_tokens,
    temperature: req.temperature,
    logger,
  });
  if (!reply.ok) return { outcome: 'skipped', detail: reply.reason + (reply.detail ? `: ${reply.detail}` : '') };

  const committed = await kernel.commit({
    taskId,
    chatResponse: { text: reply.text, usage_in: reply.usage_in, usage_out: reply.usage_out },
  });
  if (!committed.ok) return { outcome: 'error', detail: `commit ${committed.reason}` };
  return { outcome: 'done', detail: JSON.stringify(committed.data ?? {}) };
}

/**
 * 后台拉取循环：空闲等 IDLE_MS，出错指数退避，成功后立刻再取一次。
 * @returns {{ stop: () => void }}
 */
export function startExtractLoop({ ctx, config, kernel, logger }) {
  let stopped = false;
  let timer = null;
  let backoff = IDLE_MS;
  const failures = Object.create(null);

  const logFailure = (r) => {
    const key = r.detail ?? r.outcome;
    const n = (failures[key] = (failures[key] ?? 0) + 1);
    if (n <= 2 || n % 20 === 0) logger?.warn?.(`${config.logPrefix} 抽取未完成[${r.outcome}] ${key}（第 ${n} 次）`);
  };

  const schedule = (ms) => {
    if (stopped) return;
    timer = setTimeout(tick, ms);
    if (typeof timer.unref === 'function') timer.unref(); // 别拖住宿主退出
  };

  async function tick() {
    if (stopped) return;
    try {
      const r = await runOnce({ ctx, config, kernel, logger });
      if (r.outcome === 'done') {
        backoff = IDLE_MS;
        logger?.info?.(`${config.logPrefix} 抽取完成 ${r.detail ?? ''}`);
        return schedule(500); // 还有活儿就接着取
      }
      if (r.outcome === 'idle') {
        backoff = IDLE_MS;
        return schedule(IDLE_MS);
      }
      logFailure(r);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      return schedule(backoff);
    } catch (err) {
      // 循环里任何异常都不能冒出去（未处理 rejection 会杀宿主）
      logger?.warn?.(`${config.logPrefix} 抽取循环异常（已吞掉）: ${errBrief(err)}`);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
      return schedule(backoff);
    }
  }

  if (config.extractEnabled) {
    schedule(5_000); // 启动后别立刻抢资源
    logger?.info?.(`${config.logPrefix} 抽取循环已启动（空闲 ${IDLE_MS / 1000}s）`);
  }

  return {
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
      timer = null;
    },
  };
}
