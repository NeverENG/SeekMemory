/** Host-neutral runtime JSON mapping. No scheduler, model calls, or audit policy. */

const ACTIONS = new Set(['ignore', 'observe', 'wait', 'reply']);
const ATTENTION = new Set(['ambient', 'addressed', 'direct', 'private']);
const EVENTS = new Set(['accept_user', 'record_reply', 'record_delivery', 'record_error', 'action_result']);
const text = (value) => typeof value === 'string' ? value : '';
const epoch = (value) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
const cursor = (value) => Number.isSafeInteger(value) && value >= 0;

/** DSH numeric event times are milliseconds; offset-free strings are unknown. */
export function eventEpoch(value) {
  if (typeof value === 'number') return value <= 8.64e15 ? epoch(value) / 1000 : 0;
  if (typeof value !== 'string') return 0;
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$/i.exec(value);
  if (!parts) return 0;
  const [year, month, day, hour, minute, second] = parts.slice(1, 7).map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 || second > 59) return 0;
  const wall = new Date(0);
  wall.setUTCFullYear(year, month - 1, day);
  wall.setUTCHours(hour, minute, second, 0);
  if (wall.getUTCFullYear() !== year || wall.getUTCMonth() !== month - 1 || wall.getUTCDate() !== day) return 0;
  const zone = parts[8];
  const [offsetHour, offsetMinute] = zone.toUpperCase() === 'Z' ? [0, 0] : zone.slice(1).split(':').map(Number);
  if (offsetHour > 23 || offsetMinute > 59) return 0;
  const offset = (offsetHour * 60 + offsetMinute) * (zone.startsWith('-') ? -1 : 1);
  const fraction = parts[7] ? Number(`0.${parts[7]}`) : 0;
  return epoch((wall.getTime() - offset * 60_000) / 1000 + fraction);
}

export function runtimeInput({ sessionId, value, speakerId = '', privateChat = false,
  mentioned = false, eventTime = 0, receivedAt = Date.now() / 1000, scene = 'group',
  conversationId = '', threadId = '', selfId = '', role = 'member', addressed = false,
  replyToMe = false, eventId = '' }) {
  const body = text(value);
  const privateScene = privateChat === true || scene === 'private';
  return {
    session_id: text(sessionId), text: body, event_time: epoch(eventTime),
    received_at: epoch(receivedAt), speaker_id: text(speakerId), private: privateScene,
    mentioned: privateScene || mentioned === true, question: /[?？]/u.test(body),
    unread_count: 0, unread_seq: 0,
    scene: privateScene ? 'private' : ['group', 'channel', 'thread', 'comment'].includes(scene) ? scene : 'group',
    conversation_id: text(conversationId), thread_id: text(threadId), self_id: text(selfId),
    role: ['owner', 'admin', 'member', 'bot', 'system'].includes(role) ? role : 'member',
    addressed: addressed === true || mentioned === true, reply_to_me: replyToMe === true,
    event_id: text(eventId), kind: 'message',
  };
}

function receiptValid(receipt) {
  const decision = receipt?.decision;
  return ACTIONS.has(decision?.action) && ATTENTION.has(decision?.attention)
    && typeof decision.reason === 'string' && typeof decision.must_reply === 'boolean'
    && typeof receipt.source_id === 'string' && typeof receipt.turn_id === 'string'
    && (receipt.read_through_seq === null || cursor(receipt.read_through_seq));
}

/** Keep host objects, arbitrary extras, and action bodies out of result events. */
function eventPayload(kind, data) {
  const fields = {
    accept_user: ['input', 'event_id'],
    record_reply: ['run_id', 'session_id', 'text', 'speaker_id', 'turn_id', 'reply_to', 'recall_ids', 'at'],
    record_delivery: ['run_id', 'session_id', 'decision', 'reason', 'response_chars', 'tool_calls',
      'user_source_id', 'assistant_source_id', 'read_through_seq'],
    record_error: ['run_id', 'session_id', 'decision', 'reason', 'error', 'user_source_id'],
    action_result: ['action_id', 'run_id', 'session_id', 'result'],
  }[kind];
  if (!fields) return null;
  const payload = Object.fromEntries(fields.filter((key) => data[key] !== undefined).map((key) => [key, data[key]]));
  if (kind === 'accept_user') {
    const input = data.input;
    if (!input || typeof input.session_id !== 'string' || !input.session_id || typeof input.text !== 'string') return null;
    if (input.kind !== undefined && input.kind !== 'message') return null;
    const projected = runtimeInput({ sessionId: input.session_id, value: input.text, receivedAt: 0 });
    for (const key of Object.keys(projected)) {
      if (input[key] === undefined) continue;
      if (typeof input[key] !== typeof projected[key]) return null;
      if (typeof input[key] === 'number' && (!Number.isFinite(input[key]) || input[key] < 0)) return null;
      if (['unread_count', 'unread_seq'].includes(key) && !cursor(input[key])) return null;
      projected[key] = input[key];
    }
    payload.input = projected;
  } else if (typeof data.session_id !== 'string' || !data.session_id) return null;
  for (const field of ['event_id', 'run_id', 'session_id', 'text', 'speaker_id', 'turn_id', 'reply_to', 'at',
    'decision', 'reason', 'error', 'user_source_id', 'assistant_source_id', 'action_id']) {
    if (payload[field] !== undefined && typeof payload[field] !== 'string') return null;
  }
  for (const field of ['recall_ids', 'tool_calls']) {
    if (payload[field] !== undefined && (!Array.isArray(payload[field])
      || payload[field].some((item) => typeof item !== 'string'))) return null;
  }
  if (payload.response_chars !== undefined && !cursor(payload.response_chars)) return null;
  if (payload.error !== undefined && !/^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$/.test(payload.error)) payload.error = 'host_error';
  if (kind === 'record_delivery' && payload.read_through_seq !== undefined
    && payload.read_through_seq !== null && !cursor(payload.read_through_seq)) return null;
  if (kind === 'action_result') {
    if (typeof data.action_id !== 'string' || !data.action_id || typeof data.result?.ok !== 'boolean'
      || typeof data.result?.reason !== 'string' || !/^[a-z_]{0,64}$/.test(data.result.reason)) return null;
    payload.result = { ok: data.result.ok, reason: data.result.reason };
  }
  return payload;
}

export class RuntimeBridge {
  #kernel;
  #closed = false;
  #abort = new AbortController();
  #gateEnabled = false;

  constructor(kernel) { this.#kernel = kernel; }

  async #supported() {
    if (this.#closed) return { ok: false, reason: 'runtime_stopped', attempted: false };
    const health = await this.#kernel.health(this.#abort.signal);
    if (!health.ok) return { ...health, attempted: false };
    const version = health.data?.runtime_contract;
    if (version === undefined) return { ok: false, reason: 'runtime_unsupported', attempted: false };
    if (version !== 1) return { ok: false, reason: 'runtime_contract_mismatch', attempted: false };
    this.#gateEnabled = health.data?.runtime_gate_enabled === true;
    return { ok: true };
  }

  async event(kind, subjectKey, data) {
    if (!EVENTS.has(kind)) return { ok: false, reason: 'unsupported_event', attempted: false };
    const payload = eventPayload(kind, data);
    if (!payload) return { ok: false, reason: 'invalid_runtime_event', attempted: false };
    const supported = await this.#supported();
    if (!supported.ok || this.#closed) return this.#closed
      ? { ok: false, reason: 'runtime_stopped', attempted: false } : supported;
    const result = await this.#kernel.runtimeEvent({ kind, subject_key: text(subjectKey), ...payload }, this.#abort.signal);
    if (this.#closed) return { ok: false, reason: 'runtime_stopped', attempted: true };
    if (result.ok && kind === 'accept_user' && !receiptValid(result.data)) {
      return { ok: false, reason: 'invalid_runtime_receipt', attempted: true };
    }
    return { ...result, attempted: true };
  }

  async context(subjectKey, request) {
    const supported = await this.#supported();
    if (!supported.ok || this.#closed) return this.#closed
      ? { ok: false, reason: 'runtime_stopped' } : supported;
    const input = runtimeInput(request);
    if (!input.session_id) return { ok: false, reason: 'missing_session' };
    const result = await this.#kernel.runtimeContext({
      subject_key: text(subjectKey), session_id: input.session_id, query: input.text,
      source_id: text(request.sourceId), speaker_id: input.speaker_id, private: input.private,
      event_time: input.event_time, received_at: input.received_at, now: epoch(request.now ?? Date.now() / 1000),
      reason: 'inbound',
      ...(request.budgetChars === undefined ? {} : { budget_chars: request.budgetChars }),
      ...(request.k === undefined ? {} : { k: request.k }),
    }, this.#abort.signal);
    if (this.#closed) return { ok: false, reason: 'runtime_stopped' };
    if (result.ok && (typeof result.data?.text !== 'string' || !result.data?.info || typeof result.data.info !== 'object'
      || Array.isArray(result.data.info))) return { ok: false, reason: 'invalid_runtime_context' };
    return result;
  }

  applyDecision(decision, receipt) {
    if (this.#closed || !this.#gateEnabled || !receiptValid(receipt)) return decision;
    return receipt.decision.must_reply || receipt.decision.action === 'reply'
      ? decision : { ...decision, kind: 'reject' };
  }

  stop() { this.#closed = true; this.#abort.abort(); }
}
