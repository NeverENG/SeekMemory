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
import { eventEpoch, runtimeInput } from './runtime-bridge.js';

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
  return textOf(lastUserMessage(messages)?.content);
}

function lastUserMessage(messages) {
  if (!Array.isArray(messages)) return null;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    const m = messages[i];
    if (!m) continue;
    if (m.source?.kind && m.source.kind !== 'user') continue; // 注入消息/工具消息不算
    if (m.role !== 'user') continue;
    const text = textOf(m.content);
    if (text) return m;
  }
  return null;
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
export function registerHostHooks({ ctx, config, kernel, logger, runtime, disposers = [] }) {
  let stopped = false;
  const turns = new Map();
  // session id -> newest user message id, used to pair the assistant reply that follows.
  const lastUserTurn = new Map();
  disposers.push(() => { stopped = true; turns.clear(); lastUserTurn.clear(); personas.clear(); });
  const state = { subjectWarned: false };
  // persona **按主体分槽**：单槽缓存会把 A 的画像注入到 B 的上下文里
  // （只查 TTL 不查 subject = 身份/隐私 bug，review #110 第 1 条）。
  /** @type {Map<string, {text:string, revision:number, fetchedAt:number}>} */
  const personas = new Map();

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
    if (stopped) return;
    if (!config.injectPersona) return;
    const key = subjectKey || '';
    const cached = personas.get(key);
    if (cached && Date.now() - cached.fetchedAt < PERSONA_TTL_MS) return;
    const r = await kernel.persona(key);
    if (!r.ok || stopped) return;
    personas.set(key, {
      text: String(r.data?.text ?? ''),
      revision: Number(r.data?.revision ?? 0),
      fetchedAt: Date.now(),
    });
  };

  /** 读某主体的画像文本；没有就是空串（物理离场，不注入别人的）。 */
  const personaTextFor = (subjectKey) => {
    if (!config.injectPersona) return '';
    return personas.get(subjectKey || '')?.text ?? '';
  };

  // ── 1. 捕获 ──────────────────────────────────────────────
  if (config.enabled) {
    const off = ctx.on('session/event', (session, event) => {
      try {
        if (stopped) return;
        const type = event?.type;
        if (type !== 'user/message' && type !== 'assistant/message') return;
        const role = type === 'user/message' ? 'user' : 'assistant';
        const data = event.data ?? {};
        // 中间步骤的正文只是“我要去查一下”之类的旁白，真正的回复在收尾消息里。
        // 实测同一 turn 会有 100+ 条 assistant/message（reasoning/tool-call），
        // 其中带正文的中间步骤会把同一条 user 消息重复配对，必须跳过。
        const blocks = data.message?.content;
        if (role === 'assistant' && Array.isArray(blocks)
            && blocks.some((block) => block?.type === 'tool-call')) return;
        const text = role === 'assistant'
          ? textOf(data.message?.content) || textOf(data.content) || String(data.text ?? '')
          : textOf(data.content) || String(data.text ?? '');
        if (!text) return;
        // 宿主注入的消息（召回块 plugin:seekmemory、runtime-context、skill-catalog 等）
        // 不是用户输入。回灌进记忆会变成"用户说过的话"，还会被再次召回，
        // 形成自我强化污染。判据与 lastUserMessage() 一致：只认 source.kind === 'user'。
        const origin = data.source?.kind;
        if (role === 'user' && origin && origin !== 'user') return;
        const eventTime = eventEpoch(event?.time);
        const payload = {
          subject_key: deriveSubjectKey({ agent: { session } }, config, logger, state),
          session: String(session?.id ?? ''),
          role,
          text,
          at: eventTime > 0 ? new Date(eventTime * 1000).toISOString() : '',
          msg_id: String(role === 'assistant'
            ? (data.message?.id ?? data.id ?? '')
            : (data.id ?? '')),
        };
        // fire-and-forget：捕获失败不能拖慢对话。
        // **必须接 .catch()**：Node 22 下未处理的 rejection 会直接终止宿主进程。
        const input = runtimeInput({ sessionId: payload.session, value: text,
          speakerId: payload.subject_key, privateChat: session?.meta?.private === true,
          mentioned: data.mentioned === true, eventTime, eventId: payload.msg_id,
          scene: session?.meta?.scene, conversationId: session?.meta?.conversation_id,
          threadId: session?.meta?.thread_id, selfId: session?.meta?.self_id,
          role: data.role, addressed: data.addressed, replyToMe: data.reply_to_me });
        const key = JSON.stringify([payload.session, payload.msg_id]);
        const capture = (async () => {
          // A host message ID is not a Source ID: resolve the parent through its own
          // capture so reply_to carries the kernel-issued source_id.
          let replyTo = '';
          if (role === 'assistant') {
            // DSH does not name the parent message: real assistant events carry only
            // {turn, step, message:{role,content,source,id}, usage, stream}. Waiting for an
            // explicit reply_to means never pairing anything, so fall back to the last user
            // message of this same session (ordering, not content guessing).
            const explicitId = String(data.message?.reply_to ?? data.message?.replyTo ?? data.reply_to ?? '');
            const parentId = explicitId || String(lastUserTurn.get(payload.session) ?? '');
            const parent = parentId && turns.get(JSON.stringify([payload.session, parentId]));
            if (parent) {
              const result = await parent.capture;
              replyTo = String(result?.data?.source_id ?? result?.data?.receipt?.source_id ?? '');
            }
            payload.reply_to = replyTo;
            payload.speaker = 'assistant';
          }
          const r = await runtime.event(role === 'user' ? 'accept_user' : 'record_reply', payload.subject_key,
            role === 'user' ? { input, event_id: payload.msg_id } : {
              run_id: '', session_id: payload.session, text, speaker_id: 'assistant', turn_id: payload.msg_id,
              reply_to: replyTo, recall_ids: [], at: payload.at,
            });
          if (stopped) return { ok: false, reason: 'runtime_stopped' };
          // Once a runtime write was attempted, a timeout must not trigger a second capture.
          if (!r.attempted && !['runtime_stopped', 'contract_mismatch'].includes(r.reason)) return kernel.capture(payload);
          return r;
        })();
        if (role === 'user' && payload.msg_id) {
          turns.delete(key);
          turns.set(key, { capture, input });
          if (turns.size > 128) turns.delete(turns.keys().next().value);
          // Remember the newest user message per session so the following assistant reply
          // can be paired with it even though DSH never states the parent.
          lastUserTurn.delete(payload.session);
          lastUserTurn.set(payload.session, payload.msg_id);
          if (lastUserTurn.size > 256) lastUserTurn.delete(lastUserTurn.keys().next().value);
        }
        void capture
          .then((r) => {
            if (!r.ok) logCaptureFailure(r);
          })
          .catch(() => logger?.warn?.(`${config.logPrefix} 捕获异常（已跳过）`));
      } catch (err) {
        logger?.warn?.(`${config.logPrefix} 捕获失败（跳过）: ${err?.message ?? err}`);
      }
    });
    if (typeof off === 'function') disposers.push(off);
  }

  // ── 2. 每轮召回 ──────────────────────────────────────────
  if (config.enabled) {
    const handler = async (payload, next) => {
      const decision = await next();
      try {
        if (stopped) return decision;
        if (!decision || decision.kind === 'reject') return decision;
        const userMessage = lastUserMessage(payload?.messages) ?? lastUserMessage(decision.messages);
        const query = textOf(userMessage?.content);
        if (!query) return decision;

        const sk = deriveSubjectKey(payload, config, logger, state);
        // 顺手刷新人格缓存，不阻塞本轮。未处理的 rejection 会直接杀宿主进程，必须接 catch。
        void refreshPersona(sk).catch((err) =>
          logger?.warn?.(`${config.logPrefix} 人格刷新异常（已吞掉）: ${err?.message ?? err}`),
        );

        const session = payload?.agent?.session;
        const key = JSON.stringify([String(session?.id ?? ''), String(userMessage?.id ?? '')]);
        const turn = turns.get(key);
        const accepted = await turn?.capture;
        if (stopped) return decision;
        const mapped = runtime.applyDecision(decision, accepted?.ok ? accepted.data : null);
        if (mapped?.kind === 'reject') return mapped;
        if (!config.injectRecall) return decision;
        const context = await runtime.context(sk, {
          sessionId: String(session?.id ?? ''), value: query, speakerId: sk,
          privateChat: session?.meta?.private === true,
          sourceId: accepted?.ok ? accepted.data?.source_id : '',
          eventTime: turn?.input.event_time, receivedAt: turn?.input.received_at,
          budgetChars: config.budgetChars, k: config.k,
        });
        if (stopped) return decision;
        const r = context.ok ? { ok: true, data: { block: context.data.text } }
          : ['runtime_unsupported', 'runtime_contract_mismatch'].includes(context.reason)
            ? await kernel.recall({ query, subjectKey: sk, speaker: sk }) : context;
        if (stopped) return decision;
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
        if (stopped) return decision;
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
      if (stopped) return;
      if (!agent || registered.has(agent)) return;
      registered.add(agent);
      // 把上下文**绑定到该 agent 自己的主体键**：读的是 personas.get(自己的 key)，
      // 别的 agent 的画像不可能被读到（review #110 第 1 条）。
      const boundKey = deriveSubjectKey({ agent }, config, logger, state);
      try {
        const d = agent.ctx.systemPrompt.context({
          name: 'seekmemory:persona',
          order: 520,
          // text 必须是同步函数：返回缓存值，异步刷新在别处做
          text: () => personaTextFor(boundKey),
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
        if (stopped) return;
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
