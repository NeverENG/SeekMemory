import { useState } from "react"
import {
  Activity,
  BookOpen,
  FlaskConical,
  RefreshCw,
  ScrollText,
  Upload,
} from "lucide-react"
import { Badge, Button, DetailDrawer, Select } from "@/ui"
import { MemoryWorkspace } from "@/features/memory/views/memory-workspace"
import type { ManagementClient } from "../model"
import { useControl } from "../use-control"
import { ArtifactEditor } from "./artifact-editor"
import { Diagnostics } from "./diagnostics"
import { LogView } from "./log-view"
import { RuntimePanel } from "./runtime-panel"
import { RunTraces } from "./run-traces"
import { HistoryImport } from "./history-import"

const sections = [
  { id: "memory", label: "记忆库", icon: BookOpen },
  { id: "runtime", label: "运行与任务", icon: Activity },
  { id: "diagnose", label: "召回诊断", icon: FlaskConical },
  { id: "logs", label: "生命周期日志", icon: ScrollText },
  { id: "traces", label: "运行轨迹", icon: Activity },
  { id: "history-import", label: "历史初始化", icon: Upload },
] as const

const actionLabels = {
  extract: "立即抽取",
  weekly: "每周整理",
  cancel: "取消任务",
}

export function ControlWorkspace({ client }: { client: ManagementClient }) {
  const vm = useControl(client)
  const [section, setSection] =
    useState<(typeof sections)[number]["id"]>("memory")
  const [editorId, setEditorId] = useState<string | null>(null)
  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b bg-card px-4 py-3 sm:px-6">
        <nav aria-label="工作台导航" className="flex flex-wrap gap-1">
          {sections.map(({ id, label, icon: Icon }) => (
            <Button
              key={id}
              variant={section === id ? "default" : "ghost"}
              aria-pressed={section === id}
              onClick={() => setSection(id)}
            >
              <Icon className="size-4" />
              {label}
            </Button>
          ))}
        </nav>
        <div className="flex items-center gap-3">
          <Badge tone={vm.status?.ready ? "success" : "warning"}>
            {vm.status?.ready ? "引擎就绪" : "等待连接"}
          </Badge>
          <Button
            variant="ghost"
            aria-label="刷新工作台"
            onClick={() => {
              void vm.refresh()
            }}
          >
            <RefreshCw className="size-4" />
            刷新
          </Button>
        </div>
      </header>
      {vm.error && (
        <p
          role="alert"
          className="border-b border-destructive/20 bg-destructive/5 px-6 py-3 text-sm text-destructive"
        >
          {vm.error}
        </p>
      )}
      {section === "memory" && (
        <>
          <div className="flex flex-wrap items-center gap-3 border-b px-5 py-3 text-xs">
            <span className="text-muted-foreground">管理范围</span>
            <Select
              label="筛选 scope"
              value={vm.scope}
              onValueChange={vm.setScope}
              options={[
                { value: "all", label: "全部 scope" },
                { value: "private", label: "私有" },
                { value: "shared", label: "共享" },
                { value: "shadow", label: "影子" },
              ]}
            />
            <Select
              label="筛选来源会话"
              className="max-w-80"
              value={vm.session}
              onValueChange={vm.setSession}
              options={[
                { value: "all", label: "全部来源会话" },
                ...vm.sessions.map((value) => ({ value, label: value })),
              ]}
            />
            <span className="text-muted-foreground">
              管理员可查看所有家族；筛选不改变机器人访问权限。
            </span>
          </div>
          <MemoryWorkspace
            source={vm.source}
            onRetry={() => {
              void vm.refresh()
            }}
            onInspect={setEditorId}
          />
        </>
      )}
      {section === "runtime" && (
        <RuntimePanel
          status={vm.status}
          busy={vm.busy}
          onAction={vm.requestAction}
          client={client}
        />
      )}
      {section === "diagnose" && <Diagnostics client={client} />}
      {section === "logs" && <LogView events={vm.events} />}
      {section === "traces" && (
        <RunTraces client={client} onInspect={setEditorId} />
      )}
      {section === "history-import" &&
        (client.historyImport ? (
          <HistoryImport
            client={client.historyImport}
            busy={Boolean(vm.status?.activeTask)}
          />
        ) : (
          <p className="p-8 text-center text-sm text-muted-foreground">
            当前预览客户端未启用历史导入操作。
          </p>
        ))}
      <ArtifactEditor
        key={editorId}
        client={client}
        id={editorId}
        close={() => setEditorId(null)}
        onSaved={vm.refreshAfterWrite}
      />
      <DetailDrawer
        open={vm.action !== null}
        onOpenChange={(open) => {
          if (!open) vm.dismissAction()
        }}
        title="确认维护操作"
        description="确认任务影响后执行"
      >
        <div className="space-y-5 p-6">
          <h2 className="text-xl font-semibold">
            确认
            {actionLabels[vm.action ?? "cancel"]}
          </h2>
          <p className="text-sm leading-7 text-muted-foreground">
            {vm.action === "cancel"
              ? "取消会保留尚未处理的抽取消息；已经完成的写入不会撤销。同步整理开始后可能已完成，取消并不保证回滚。"
              : "此操作会修改真实记忆数据。旧版本和已写入的账本会保留；抽取还可能产生模型调用费用。"}
          </p>
          <label className="flex gap-2 text-sm">
            <input
              type="checkbox"
              checked={vm.confirmed}
              onChange={(event) => vm.setConfirmed(event.target.checked)}
            />
            我已确认本次操作及其影响
          </label>
          <Button
            disabled={!vm.confirmed || vm.busy}
            onClick={() => {
              void vm.executeAction()
            }}
          >
            确认执行
          </Button>
        </div>
      </DetailDrawer>
    </div>
  )
}
