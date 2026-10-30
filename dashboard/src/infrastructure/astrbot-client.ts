import { managementClient } from "./management-client.ts"

interface PluginBridge {
  ready(): Promise<unknown>
  apiGet(endpoint: string, query?: Record<string, string>): Promise<unknown>
  apiPost(endpoint: string, body: unknown): Promise<unknown>
}
declare global {
  interface Window {
    AstrBotPluginPage?: PluginBridge
  }
}

async function bridge(): Promise<PluginBridge> {
  const current = window.AstrBotPluginPage
  if (!current)
    throw new Error("请从 AstrBot 的 SeekMemory 插件视图打开此页面。")
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    await Promise.race([
      current.ready(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error("宿主连接超时，请重新打开插件视图。")),
          10000
        )
      }),
    ])
  } finally {
    if (timer !== undefined) clearTimeout(timer)
  }
  return current
}

export const astrbotClient = managementClient(bridge)
