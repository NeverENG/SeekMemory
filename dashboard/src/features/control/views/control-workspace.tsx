import { useState } from "react"
import { Button, DetailDrawer, Select } from "@/ui"
import { systemSections } from "../sections"
import { FilterChoices } from "@/features/memory/views/memory-filters"
import {
  scopeLabels,
  scopeDescriptions,
} from "@/features/memory/views/presentation"
import { MemoryWorkspace } from "@/features/memory/views/memory-workspace"
import type { ManagementClient } from "../model"
import { useControl } from "../use-control"
import { ArtifactEditor } from "./artifact-editor"
import { Diagnostics } from "./diagnostics"
import { LogView } from "./log-view"
import { RuntimePanel } from "./runtime-panel"
import { RunTraces } from "./run-traces"

const actionLabels = {
  extract: "立即抽取",
  weekly: "每周整理",
  cancel: "取消任务",
}

export function ControlWorkspace({
  client,
  initialSection,
  initialRun,
}: {
  client: ManagementClient
  initialSection?: string | undefined
  initialRun?: string
}) {
  const vm = useControl(client)
  const section =
    initialSection === "memory"
      ? "memory"
      : (systemSections.find((item) => item.id === initialSection)?.id ??
        "runtime")
  const [editorId, setEditorId] = useState<string | null>(null)
  return (
    <div className="flex min-h-full flex-col">
      {vm.error && (
        <p
          role="alert"
          className="border-b border-destructive/20 bg-destructive/5 px-6 py-3 text-sm text-destructive"
        >
          {vm.error}
        </p>
      )}
      {section === "memory" && (
        <MemoryWorkspace
          source={vm.source}
          onRetry={() => {
            void vm.refresh()
          }}
          onInspect={setEditorId}
          filters={{
            selections: [
              ...(vm.scope === "all"
                ? []
                : [
                    {
                      label: `范围：${scopeLabels[vm.scope]}`,
                      onClear: () => vm.setScope("all"),
                    },
                  ]),
              ...(vm.session === "all"
                ? []
                : [
                    {
                      label: `会话：${vm.session}`,
                      onClear: () => vm.setSession("all"),
                    },
                  ]),
            ],
            onReset: () => {
              vm.setScope("all")
              vm.setSession("all")
            },
            controls: (
              <>
                <FilterChoices
                  label="使用范围"
                  value={vm.scope}
                  onChange={vm.setScope}
                  options={[
                    { value: "all", label: "不限范围" },
                    ...(["private", "shared", "shadow"] as const).map(
                      (value) => ({
                        value,
                        label: scopeLabels[value],
                        description: scopeDescriptions[value],
                      })
                    ),
                  ]}
                />
                <div>
                  <label
                    htmlFor="memory-session-filter"
                    className="mb-3 block text-sm font-medium"
                  >
                    来源会话
                  </label>
                  <Select
                    id="memory-session-filter"
                    label="筛选来源会话"
                    className="w-full max-w-full"
                    value={vm.session}
                    onValueChange={vm.setSession}
                    options={[
                      { value: "all", label: "全部来源会话" },
                      ...vm.sessions.map((value) => ({ value, label: value })),
                    ]}
                  />
                </div>
              </>
            ),
          }}
        />
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
      {section === "logs" && <LogView client={client} />}
      {section === "traces" && (
        <RunTraces
          client={client}
          onInspect={setEditorId}
          initialRun={initialRun ?? ""}
        />
      )}
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
