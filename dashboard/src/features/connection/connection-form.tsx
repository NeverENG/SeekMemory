import { useState } from "react"
import { Button, Input } from "@/ui"

export function ConnectionForm({
  defaultUrl,
  notice,
  onConnect,
}: {
  defaultUrl: string
  notice: string
  onConnect: (url: string, token: string) => Promise<void>
}) {
  const [url, setUrl] = useState(defaultUrl)
  const [token, setToken] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background p-5 text-foreground">
      <form
        className="surface-panel w-full max-w-md space-y-6 p-6 sm:p-9"
        onSubmit={(event) => {
          event.preventDefault()
          if (busy) return
          setError("")
          setBusy(true)
          void onConnect(url.trim(), token)
            .catch(() => {
              setToken("")
              setError("连接失败，请检查 API 地址、管理员令牌及服务状态。")
            })
            .finally(() => setBusy(false))
        }}
      >
        <div>
          <p className="text-sm text-muted-foreground">SeekMemory</p>
          <h1 className="mt-2 text-2xl font-semibold">连接记忆控制台</h1>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            输入本机服务地址和管理员令牌，查看与管理记忆。
          </p>
        </div>
        <div className="space-y-2">
          <label htmlFor="console-api" className="text-sm font-medium">
            API 地址
          </label>
          <Input
            id="console-api"
            type="url"
            required
            value={url}
            disabled={busy}
            onChange={(event) => setUrl(event.target.value)}
            autoComplete="off"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor="console-token" className="text-sm font-medium">
            管理员令牌
          </label>
          <Input
            id="console-token"
            type="password"
            required
            value={token}
            disabled={busy}
            onChange={(event) => setToken(event.target.value)}
            autoComplete="off"
            aria-describedby="token-help"
          />
          <p
            id="token-help"
            className="text-xs leading-5 text-muted-foreground"
          >
            令牌仅用于当前页面；刷新或断开后需要重新输入。
          </p>
        </div>
        {(error || notice) && (
          <p role="alert" className="text-sm text-destructive">
            {error || notice}
          </p>
        )}
        <Button className="w-full" type="submit" disabled={busy}>
          {busy ? "正在连接…" : "连接控制台"}
        </Button>
      </form>
    </main>
  )
}
