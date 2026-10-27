/**
 * 唯一的 DSH 特定文件（《方案 v2.1》G12：换宿主要改的地方只有这里）。
 *
 * 用到的扩展点只有四个，全部来自已核实的实现：
 *   ctx.on('session/event')                      捕获
 *   ctx.on('agent/pre-step', fn, {prepend:true}) 每轮召回（先 next() 再改写 decision）
 *   agent.ctx.systemPrompt.context({...})        常驻人格块
 *   ctx.on('agent/created')                      新 agent 注册
 *
 * 每个钩子内部都自己兜住异常：钩子里抛出去的错会冒到宿主，按 G13 的教训
 * （插件树全有或全无），宁可这一轮不注入，也不能让异常跑到 loader。
 */

import { buildUserMessage } from './message.js';

const PLUGIN_KIND = 'plugin:seekmemory';
const PERSONA_TTL_MS = 60_000;

/** 从 content blocks 里取纯文本。 */
export function textOf(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  const parts = [];
  for (const block of content) {
    if (block && block.type === 'text' && typeof block.text === 'string') parts.push(block.text);
  }
  return parts.join('\n').trim();
}

/** 取最后一条真实用户消息的文本（跳过我们自己注入的）。 */
export function lastUserText(messages) {
  if (!Array.isArray(messages)) return '';
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (!m) continue;
    if (m.source?.kind && m.source.kind !== 'user') continue; // 注入消息/工具消息不算
    if (m.role !== 'user') continue;
    const text = textOf(m.content);
    if (text) return text;
  }
  return '';
}

/**
 * 主体键：**绝不用 session.id**（重建即变，失效是静默的）。
 * 优先取会话元数据里的稳定标识；取不到就退固定键，并明确告警一次。
 */
export function deriveSubjectKey(payload, config, logger, state) {
  if (config.subjectMode === 'fixed' || config.subjectKey) {
    return config.subjectKey || 'local:single:default';
  }
  const session = payload?.agent?.session;
  const candidates = [
    session?.subjectKey,
    session?.umo,
    session?.ownerUmo,
    session?.meta?.subjectKey,
    session?.meta?.umo,
    payload?.agent?.meta?.umo,
  ];
  for (const c of candidates) {
    if (typeof c === 'string' && c.trim()) return c.trim();
  }
  if (!state.subjectWarned) {
    state.subjectWarned = true;
    logger?.warn?.(
      `${config.logPrefix} 会话元数据里没有稳定主体键，已退化为固定键 local:single:default（owner_only 语义）`,
    );
  }
  return config.subjectKey || 'local:single:default';
}

/**
 * @param {{ ctx:any, config:any, kernel:any, logger:any }} deps
 * @returns {{ disposers: Function[] }}
 */
export function registerHostHooks({ ctx, config, kernel, logger }) {
  const disposers = [];
  const state = { subjectWarned: false };
  const persona = { text: '', revision: 0, fetchedAt: 0 };

  // 捕获失败必须有声音，但不能刷屏：每种原因记前 3 次，之后每 50 次记一次。
  // 以前这里是完全静默的，用户侧表现是"聊了半天，一条都没记住"。
  const captureFailures = Object.create(null);
  const logCaptureFailure = (r) => {
    const n = (captureFailures[r.reason] = (captureFailures[r.reason] ?? 0) + 1);
    if (n <= 3 || n % 50 === 0) {
      logger?.warn?.(`${config.logPrefix} 捕获失败 reason=${r.reason}（第 ${n} 次，这条消息没进记忆）`);
    }
  };

  const refreshPersona = async (subjectKey) => {
    if (!config.injectPersona) return;
    if (Date.now() - persona.fetchedAt < PERSONA_TTL_MS) return;
    const r = await kernel.persona(subjectKey);
    if (!r.ok) return;
    persona.text = String(r.data?.text ?? '');
    persona.revision = Number(r.data?.revision ?? 0);
    persona.fetchedAt = Date.now();
  };

  // ── 1. 捕获 ──────────────────────────────────────────────
  if (config.enabled) {
    const off = ctx.on('session/event', (session, event) => {
      try {
        const type = event?.type;
        if (type !== 'user/message' && type !== 'assistant/message') return;
        const role = type === 'user/message' ? 'user' : 'assistant';
        const data = event.data ?? {};
        const text = textOf(data.content) || String(data.text ?? '');
        if (!text) return;
        const payload = {
          subject_key: deriveSubjectKey({ agent: { session } }, config, logger, state),
          session: String(session?.id ?? ''),
          role,
          text,
          at: new Date(event?.time ?? Date.now()).toISOString(),
          msg_id: String(data.id ?? ''),
        };
        // fire-and-forget：捕获失败不能拖慢对话。
        // **必须接 .catch()**：Node 22 下未处理的 rejection 会直接终止宿主进程。
        void kernel
          .capture(payload)
          .then((r) => {
            if (!r.ok) logCaptureFailure(r);
          })
          .catch((err) => logger?.warn?.(`${config.logPrefix} 捕获异常（已吞掉）: ${err?.message ?? err}`));
      } catch (err) {
        logger?.warn?.(`${config.logPrefix} 捕获失败（跳过）: ${err?.message ?? err}`);
      }
    });
    if (typeof off === 'function') disposers.push(off);
  }

  // ── 2. 每轮召回 ──────────────────────────────────────────
  if (config.enabled && config.injectRecall) {
    const handler = async (payload, next) => {
      const decision = await next();
      try {
        if (!decision || decision.kind === 'reject') return decision;
        const query = lastUserText(payload?.messages) || lastUserText(decision.messages);
        if (!query) return decision;

        const sk = deriveSubjectKey(payload, config, logger, state);
        // 顺手刷新人格缓存，不阻塞本轮。未处理的 rejection 会直接杀宿主进程，必须接 catch。
        void refreshPersona(sk).catch((err) =>
          logger?.warn?.(`${config.logPrefix} 人格刷新异常（已吞掉）: ${err?.message ?? err}`),
        );

        const r = await kernel.recall({ query, subjectKey: sk });
        if (!r.ok) {
          logger?.warn?.(`${config.logPrefix} 召回跳过（${r.reason}）`);
          return decision;
        }
        const block = String(r.data?.block ?? '');
        if (!block) return decision;

        // 内核返回的 block 已自带 <relevant-memories> 帧，这里不再二次包裹
        const injection = await buildUserMessage({
          text: block,
          kind: PLUGIN_KIND,
          form: 'recall',
          logger,
          envelope: false,
        });
        // 展开 decision：只替换 messages，保留宿主塞进来的 usage / stepId 等字段
        // （原实现 new 一个 {kind,messages}，把这些字段丢了）
        return { ...decision, kind: 'enter', messages: [injection, ...(decision.messages ?? [])] };
      } catch (err) {
        logger?.warn?.(`${config.logPrefix} 召回注入失败（跳过本轮）: ${err?.message ?? err}`);
        return decision;
      }
    };
    const off = ctx.on('agent/pre-step', handler, { prepend: true });
    if (typeof off === 'function') disposers.push(off);
  }

  // ── 3. 人格块（稳定区） ──────────────────────────────────
  if (config.enabled && config.injectPersona) {
    const registered = new WeakSet();
    const registerFor = (agent) => {
      if (!agent || registered.has(agent)) return;
      registered.add(agent);
      try {
        const d = agent.ctx.systemPrompt.context({
          name: 'seekmemory:persona',
          order: 520,
          // text 必须是同步函数：返回缓存值，异步刷新在别处做
          text: () => (config.injectPersona ? persona.text : ''),
        });
        if (typeof d === 'function') disposers.push(d);
      } catch (err) {
        logger?.warn?.(`${config.logPrefix} 人格注册失败（降级为不注入）: ${err?.message ?? err}`);
      }
    };

    try {
      const agents = ctx.get?.('agents');
      if (agents?.list) for (const a of agents.list()) registerFor(a);
    } catch {
      /* 取不到已存在 agent 就算了，后续 agent/created 会补 */
    }

    const off = ctx.on('agent/created', async (payload) => {
      try {
        const agent = payload?.agent;
        registerFor(agent);
        await refreshPersona(deriveSubjectKey(payload, config, logger, state));
      } catch (err) {
        logger?.warn?.(`${config.logPrefix} agent/created 处理失败: ${err?.message ?? err}`);
      }
    });
    if (typeof off === 'function') disposers.push(off);
  }

  return { disposers };
}
