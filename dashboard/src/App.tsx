import { lazy, Suspense } from "react"
import { ConsoleWorkspace } from "@/features/shell/console-workspace"
import { astrbotClient } from "@/infrastructure/astrbot-client"
import { StandaloneApp } from "./StandaloneApp"

// Vite 会从生产构建中移除此分支及其示例数据导入。
const MockApp =
  import.meta.env.DEV && import.meta.env.MODE === "mock"
    ? lazy(() => import("@/dev/MockApp"))
    : null

export default function App() {
  if (MockApp) {
    return (
      <Suspense
        fallback={
          <p role="status" className="p-8 text-sm text-muted-foreground">
            正在加载预览…
          </p>
        }
      >
        <MockApp />
      </Suspense>
    )
  }

  if (import.meta.env.MODE === "host" || window.AstrBotPluginPage) {
    return <ConsoleWorkspace client={astrbotClient} />
  }
  const defaultUrl = import.meta.env.DEV
    ? "http://127.0.0.1:8766/api/"
    : new URL("/api/", window.location.href).href
  return <StandaloneApp defaultUrl={defaultUrl} />
}
