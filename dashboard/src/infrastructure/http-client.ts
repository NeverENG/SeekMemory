import { managementClient } from "./management-client.ts"

export function consoleBaseUrl(value: string): URL {
  const url = new URL(value)
  if (
    url.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(url.hostname) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  )
    throw new Error("请输入本机 HTTP API 地址，例如 http://127.0.0.1:8766/api/")
  url.pathname = url.pathname.replace(/\/*$/, "/")
  return url
}

export function httpClient(
  baseUrl: string,
  token: string,
  options: { signal: AbortSignal; onUnauthorized: () => void }
) {
  const base = consoleBaseUrl(baseUrl)
  async function request(
    endpoint: string,
    method: "GET" | "POST",
    query?: Record<string, string>,
    body?: unknown
  ): Promise<unknown> {
    const url = new URL(endpoint, base)
    for (const [key, value] of Object.entries(query ?? {}))
      url.searchParams.set(key, value)
    let response: Response
    try {
      response = await fetch(url, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(method === "POST" ? { "Content-Type": "application/json" } : {}),
        },
        ...(method === "POST" ? { body: JSON.stringify(body) } : {}),
        signal: AbortSignal.any([options.signal, AbortSignal.timeout(15000)]),
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
        referrerPolicy: "no-referrer",
      })
    } catch {
      if (options.signal.aborted) throw new Error("连接已结束")
      throw new Error("无法连接 API，请检查服务地址及允许访问的页面来源。")
    }
    if (options.signal.aborted) throw new Error("连接已结束")
    if (response.status === 401) {
      options.onUnauthorized()
      throw new Error("管理员令牌无效或已更换，请重新连接。")
    }
    if (!response.ok) {
      if (response.status === 409)
        throw new Error("内容已被修改，请重新加载并核对后再提交。")
      if (response.status === 400)
        throw new Error("请求参数无效，请检查输入内容。")
      if (response.status === 403) throw new Error("此页面来源未获 API 允许。")
      if (response.status === 404)
        throw new Error("记忆、人格包或 API 地址不存在。")
      if (response.status === 413)
        throw new Error("提交内容过大，请缩小后再试。")
      if (response.status === 503) throw new Error("当前服务未启用此操作。")
      throw new Error(`API 请求失败（${response.status}），请检查服务状态。`)
    }
    try {
      const data: unknown = await response.json()
      return data
    } catch {
      throw new Error("API 返回了无效 JSON，请检查地址与服务版本。")
    }
  }
  return managementClient(async () => ({
    apiGet: (endpoint, query) => request(endpoint, "GET", query),
    apiPost: (endpoint, body) => request(endpoint, "POST", undefined, body),
  }))
}
