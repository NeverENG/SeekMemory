import { ResourceState } from "./page-parts"
import { useCallback, useState } from "react"
import { Button } from "@/ui"
import type { ManagementClient } from "@/features/control/model"
import { ArtifactEditor } from "@/features/control/views/artifact-editor"
import { ControlWorkspace } from "@/features/control/views/control-workspace"
import { HomePage } from "@/features/home/views/home-page"
import { PersonaPage } from "@/features/persona/views/persona-page"
import { MemoryMap } from "@/features/memory-graph/views/memory-map"
import { ImpressionsPage } from "@/features/impressions/views/impressions-page"
import { DreamPage } from "@/features/dream/views/dream-page"
import { StorePage } from "@/features/persona-store/views/store-page"
import { useRoute } from "./routing"
import { useResource } from "./use-resource"
import { Sidebar } from "./sidebar"
import "./console.css"
import "./console-effects.css"

export function ConsoleWorkspace({ client }: { client: ManagementClient }) {
  const route = useRoute()
  const [collapsed, setCollapsed] = useState(false)
  const readDetail = useCallback((id: string) => client.detail(id), [client])
  const read = useCallback(() => client.status(), [client])
  const status = useResource(read)
  const [editor, setEditor] = useState<string | null>(null),
    [generation, setGeneration] = useState(0)
  const afterSave = async () => {
    await status.reload()
    setGeneration((v) => v + 1)
  }
  const consoleClient = client.console
  let content
  switch (route.page) {
    case "home":
      content = (
        <HomePage
          client={client}
          status={status.data}
          loading={status.loading}
        />
      )
      break
    case "persona":
    case "studio":
      if (status.loading || status.error) {
        content = (
          <ResourceState
            loading={status.loading}
            error={status.error}
            onRetry={status.reload}
          />
        )
        break
      }
      content = (
        <PersonaPage
          client={client}
          status={status.data}
          revision={route.revision}
          onInspect={setEditor}
          studio={route.page === "studio"}
          onSaved={status.reload}
        />
      )
      break
    case "memory":
      content = consoleClient && (
        <MemoryMap
          client={consoleClient}
          readDetail={readDetail}
          initialNode={route.node}
          onInspect={setEditor}
        />
      )
      break
    case "impressions":
      content = consoleClient && (
        <ImpressionsPage client={consoleClient} onInspect={setEditor} />
      )
      break
    case "dream":
      content = consoleClient && (
        <DreamPage client={consoleClient} status={status.data} />
      )
      break
    case "store":
      content = consoleClient && (
        <StorePage
          client={consoleClient}
          status={status.data}
          readPersona={(id) => client.detail(id)}
          onSaved={status.reload}
        />
      )
      break
    case "library":
      content = <ControlWorkspace client={client} initialSection="memory" />
      break
    case "traces":
    case "system":
      content = (
        <ControlWorkspace
          client={client}
          initialSection={route.section}
          initialRun={route.node}
        />
      )
      break
  }
  return (
    <div
      className={`console-workspace ${collapsed ? "sidebar-collapsed" : ""}`}
    >
      <Sidebar
        page={route.page}
        section={route.section}
        collapsed={collapsed}
        onToggle={() => setCollapsed(!collapsed)}
        ready={!!status.data?.ready}
        loading={status.loading}
        onRefresh={() => {
          void afterSave()
        }}
      />
      <div className="console-content">
        {status.error && (
          <div role="alert" className="console-status-error">
            {status.error}
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void status.reload()
              }}
            >
              重试连接
            </Button>
          </div>
        )}
        <main
          key={`${route.page}-${route.section ?? ""}-${route.node}-${route.revision}-${generation}`}
        >
          {content || (
            <div className="console-empty">
              当前宿主尚未提供此控制台接口，请更新插件。
            </div>
          )}
        </main>
      </div>
      <ArtifactEditor
        key={editor}
        client={client}
        id={editor}
        close={() => setEditor(null)}
        onSaved={afterSave}
      />
    </div>
  )
}
