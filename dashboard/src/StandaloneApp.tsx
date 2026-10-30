import { useState } from "react"
import { httpClient, consoleBaseUrl } from "./infrastructure/http-client"
import { ConnectionForm } from "./features/connection/connection-form"
import { ConsoleWorkspace } from "./features/shell/console-workspace"
import { Button } from "./ui"

export function StandaloneApp({ defaultUrl }: { defaultUrl: string }) {
  const [session, setSession] = useState<{
    client: ReturnType<typeof httpClient>
    controller: AbortController
    url: string
  } | null>(null)
  const [notice, setNotice] = useState("")
  const disconnect = () => {
    session?.controller.abort()
    setSession(null)
    setNotice("")
  }
  if (!session)
    return (
      <ConnectionForm
        defaultUrl={defaultUrl}
        notice={notice}
        onConnect={async (url, token) => {
          const controller = new AbortController()
          const client = httpClient(url, token, {
            signal: controller.signal,
            onUnauthorized: () => {
              controller.abort()
              setSession(null)
              setNotice("管理员令牌无效或已更换，请重新连接。")
            },
          })
          try {
            await client.status()
            setNotice("")
            setSession({ client, controller, url: consoleBaseUrl(url).href })
          } catch (error) {
            controller.abort()
            throw error
          }
        }}
      />
    )
  return (
    <div className="standalone-console flex min-h-dvh flex-col">
      <div className="sticky top-0 z-40 flex h-12 shrink-0 items-center justify-between gap-3 border-b bg-background px-5 text-sm text-muted-foreground">
        <span className="min-w-0 truncate" title={session.url}>
          已连接 · {session.url}
        </span>
        <Button variant="ghost" size="sm" onClick={disconnect}>
          断开连接
        </Button>
      </div>
      <ConsoleWorkspace client={session.client} />
    </div>
  )
}
