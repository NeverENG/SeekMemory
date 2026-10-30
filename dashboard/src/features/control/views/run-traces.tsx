import { Badge, Button, Select } from "@/ui"
import type { ManagementClient } from "../model"
import { traceFlagLabels } from "../trace-model"
import { useRunTraces } from "../use-run-traces"
import { TraceStep, eventLabels } from "./trace-step"
import { TraceQueryForm } from "./trace-query-form"

const runLabels = {
  running: "进行中",
  completed: "已完成",
  error: "发生错误",
  interrupted: "上次运行未结束",
}

export function RunTraces({
  client,
  onInspect,
  initialRun = "",
}: {
  client: ManagementClient
  initialRun?: string
  onInspect: (id: string) => void
}) {
  const vm = useRunTraces(client, initialRun)
  const lastStep = vm.timeline.at(-1)
  return (
    <section className="mx-auto w-full max-w-7xl space-y-5 p-5 sm:p-8">
      <div className="workspace-intro">
        <h1 className="text-2xl font-semibold">运行轨迹</h1>
      </div>
      <TraceQueryForm onQuery={vm.applyQuery} initialRun={initialRun} />
      {vm.error && (
        <p role="alert" className="text-sm text-destructive">
          {vm.error}
        </p>
      )}
      {vm.snapshot?.persistence_error && (
        <p role="alert" className="text-sm text-destructive">
          轨迹保存失败，当前记录可能不完整。聊天功能不受影响。
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          label="筛选运行轨迹"
          value={vm.filter}
          onValueChange={vm.setFilter}
          options={[
            { value: "all", label: "全部运行" },
            { value: "not_recalled", label: traceFlagLabels.not_recalled },
            {
              value: "recalled_but_withheld",
              label: traceFlagLabels.recalled_but_withheld,
            },
            {
              value: "recalled_and_injected",
              label: traceFlagLabels.recalled_and_injected,
            },
            { value: "fallback_used", label: traceFlagLabels.fallback_used },
          ]}
        />
        <Button
          variant="outline"
          disabled={vm.loading}
          onClick={() => {
            void vm.refresh()
          }}
        >
          刷新轨迹
        </Button>
        <p className="w-full text-xs text-muted-foreground">
          {vm.total} 次运行
          {vm.snapshot &&
            ` · 保留 ${vm.snapshot.retention_days} 天，最多 ${vm.snapshot.capacity} 条事件`}
        </p>
      </div>
      {vm.loading && (
        <p role="status" className="py-6 text-sm text-muted-foreground">
          正在读取运行轨迹…
        </p>
      )}
      {!vm.loading && !vm.error && vm.total === 0 && (
        <p className="surface-panel p-10 text-center text-sm text-muted-foreground">
          暂无匹配轨迹。请调整查询条件，并确认服务已加载运行记录。
        </p>
      )}
      {vm.active && (
        <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <div className="surface-panel max-h-[70vh] space-y-1 overflow-y-auto p-2">
            {vm.runs.map((run) => (
              <button
                key={run.id}
                aria-pressed={run.id === vm.active?.id}
                onClick={() => vm.select(run.id)}
                className="w-full space-y-2 rounded-lg p-3 text-left hover:bg-muted aria-pressed:bg-primary/10"
              >
                <div className="flex items-center justify-between gap-2 text-sm">
                  <time>{new Date(run.started_at).toLocaleString()}</time>
                  <span>{runLabels[run.status]}</span>
                </div>
                <p className="font-mono text-xs text-muted-foreground">
                  {run.id.slice(0, 12)} · {run.event_count} 个步骤
                </p>
                <div className="flex flex-wrap gap-1">
                  {run.flags.map((flag) => (
                    <Badge key={flag} variant="secondary">
                      {traceFlagLabels[flag]}
                    </Badge>
                  ))}
                </div>
              </button>
            ))}
            {vm.total > vm.runs.length && (
              <Button variant="ghost" onClick={vm.showMore}>
                加载更多
              </Button>
            )}
          </div>
          <div className="surface-panel min-w-0 p-5 sm:p-6">
            <div className="mb-6 flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">运行时间轴</h2>
              <Badge tone={vm.active.delivered ? "success" : "info"}>
                {vm.active.delivered ? "回复已发送" : "未记录发送成功"}
              </Badge>
            </div>
            <p className="mb-4 font-mono text-xs break-all text-muted-foreground">
              {vm.active.id}
            </p>
            {vm.timeline.some((event) => event.status === "error") && (
              <p role="status" className="mb-4 text-sm text-destructive">
                失败步骤：
                {vm.timeline
                  .filter((event) => event.status === "error")
                  .map((event) => eventLabels[event.event])
                  .join("、")}
              </p>
            )}
            {vm.active.status === "interrupted" && (
              <p className="mb-4 text-sm text-muted-foreground">
                未记录运行结束；最后步骤：
                {lastStep ? eventLabels[lastStep.event] : "未知"}
                。无法据此确认失败原因。
              </p>
            )}
            {vm.active.partial && (
              <p className="mb-5 text-xs text-muted-foreground">
                这次运行的部分步骤未保留，时间轴可能不完整。
              </p>
            )}
            <ol className="ml-1">
              {vm.timeline.map((event) => (
                <TraceStep
                  key={`${event.run_id}-${event.sequence}`}
                  event={event}
                  onInspect={onInspect}
                />
              ))}
            </ol>
          </div>
        </div>
      )}
    </section>
  )
}
