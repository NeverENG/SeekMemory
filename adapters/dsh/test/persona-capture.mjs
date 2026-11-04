import assert from 'node:assert/strict';
import test from 'node:test';
import { setTimeout as pause } from 'node:timers/promises';
import { registerHostHooks } from '../src/host-dsh.js';

test('assistant text blocks and explicit same-session parent reach capture', async () => {
  const handlers = new Map();
  const calls = [];
  const ctx = { on(name, fn) { handlers.set(name, fn); return () => handlers.delete(name); } };
  const kernel = { async capture(body) {
    calls.push(body);
    return { ok: true, data: { source_id: body.role === 'user' ? 'source-user-1' : 'source-assistant-1' } };
  } };
  const runtime = { async event() { return { ok: false, attempted: false, reason: 'runtime_unsupported' }; } };
  registerHostHooks({ ctx, kernel, runtime, config: {
    enabled: true, injectRecall: false, injectPersona: false, subjectMode: 'fixed',
    subjectKey: 'lab:persona', logPrefix: 'test',
  }, logger: { warn() {} } });
  const session = { id: 'session-1', meta: { private: true } };
  const event = handlers.get('session/event');
  event(session, { type: 'user/message', data: {
    id: 'host-user-1', source: { kind: 'user' }, content: [{ type: 'text', text: 'help' }],
  } });
  event(session, { type: 'assistant/message', data: { message: {
    id: 'host-assistant-step', reply_to: 'host-user-1', content: [
      { type: 'reasoning', text: 'private reasoning' },
      { type: 'tool-call', text: 'tool arguments' },
      { type: 'text', text: 'Let me check' },
    ],
  } } });
  event(session, { type: 'assistant/message', data: { message: {
    id: 'host-assistant-1', reply_to: 'host-user-1', content: [
      { type: 'reasoning', text: 'private reasoning' },
      { type: 'text', text: 'I can help' },
    ],
  } } });
  for (let i = 0; i < 50 && calls.length < 2; i += 1) await pause(5);
  await pause(20);
  assert.equal(calls.length, 2, 'the tool-step narration must not be captured');
  assert.equal(calls[0].text, 'help');
  assert.equal(calls[1].text, 'I can help');
  assert.equal(calls[1].msg_id, 'host-assistant-1');
  assert.equal(calls[1].reply_to, 'source-user-1');
});

test('without an explicit parent the reply pairs with the latest user of that session', async () => {
  const handlers = new Map();
  const calls = [];
  const ctx = { on(name, fn) { handlers.set(name, fn); return () => handlers.delete(name); } };
  const kernel = { async capture(body) {
    calls.push(body);
    return { ok: true, data: { source_id: `source-${body.msg_id}` } };
  } };
  const runtime = { async event() { return { ok: false, attempted: false, reason: 'runtime_unsupported' }; } };
  registerHostHooks({ ctx, kernel, runtime, config: {
    enabled: true, injectRecall: false, injectPersona: false, subjectMode: 'fixed',
    subjectKey: 'lab:persona', logPrefix: 'test',
  }, logger: { warn() {} } });
  const session = { id: 'session-2', meta: { private: true } };
  const event = handlers.get('session/event');
  event(session, { type: 'user/message', data: {
    id: 'host-user-2', source: { kind: 'user' }, content: [{ type: 'text', text: 'first' }],
  } });
  event(session, { type: 'user/message', data: {
    id: 'host-user-3', source: { kind: 'user' }, content: [{ type: 'text', text: 'latest' }],
  } });
  event(session, { type: 'assistant/message', data: { message: {
    id: 'host-assistant-3', content: [{ type: 'text', text: 'answer' }],
  } } });
  for (let i = 0; i < 50 && calls.length < 3; i += 1) await pause(5);
  assert.equal(calls.length, 3);
  assert.equal(calls[2].reply_to, 'source-host-user-3');
});
