/**
 * 构造注入用的 user 消息。
 *
 * 这里有一处与《方案 v2.1》G13 的**有意偏离**，必须写清楚：
 * 宿主提供的 `createUserMessage` 来自 `@deepseek-ai/dsh-llm`，是**值导入**，
 * 而 G13 要求"绝不值导入宿主内部符号"（因为符号被删会让整棵插件树加载失败）。
 *
 * 解法：**动态 import**。它在 apply() 内部执行，失败只会进 catch，
 * 不会波及模块加载；拿不到就用手工兜底形状（最小可接受消息）。
 * 代价：兜底形状的 id 前缀是我们自己造的，宿主若严格校验 id 会露馅——
 * 所以兜底路径必须打日志，不能悄悄用。
 */

import { randomUUID } from 'node:crypto';

// 缓存**promise**而不是布尔：缓存布尔时，两个并发调用会双双穿过 `resolved`
// 判断（第一个刚置位、还没 await 完），第二个就拿到 null 走兜底——是竞态。
let loadPromise = null;
let loadedFactory = null;

function load() {
  if (!loadPromise) {
    loadPromise = import('@deepseek-ai/dsh-llm')
      .then((mod) => {
        loadedFactory = typeof mod?.createUserMessage === 'function' ? mod.createUserMessage : null;
        return loadedFactory;
      })
      .catch(() => {
        loadedFactory = null;
        return null;
      });
  }
  return loadPromise;
}

/**
 * @param {{ text: string, kind: string, form: string, logger?: {warn:Function}, envelope?: boolean }} opts
 * @returns {Promise<object>} 消息对象
 */
export async function buildUserMessage({ text, kind, form, logger, envelope = true }) {
  const body = envelope
    ? `<relevant-memories>\n${text}\n</relevant-memories>`
    : text;

  const create = await load();
  if (create) {
    return create({
      content: [{ type: 'text', text: body }],
      source: { kind, form },
    });
  }

  // 兜底：手工形状。只在宿主模块不可用时走到这里。
  logger?.warn?.(`${kind}: 宿主未导出 createUserMessage，使用兜底消息形状`);
  return {
    id: `plugin:${kind}:${randomUUID()}`,
    role: 'user',
    time: Date.now(),
    content: [{ type: 'text', text: body }],
    source: { kind, form },
  };
}

/** 供测试/诊断：宿主构造函数是否已加载成功（不触发加载）。 */
export function hostMessageFactoryAvailable() {
  return typeof loadedFactory === 'function';
}
