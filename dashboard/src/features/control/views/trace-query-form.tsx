import { useId, useState } from "react"
import { Button, Input, Select } from "@/ui"
import type { TraceQuery } from "../../../contracts/api"

export function TraceQueryForm({
  onQuery,
  initialRun = "",
}: {
  onQuery: (query: TraceQuery) => void
  initialRun?: string
}) {
  const id = useId()
  const [runId, setRunId] = useState(initialRun)
  const [status, setStatus] = useState<NonNullable<TraceQuery["status"]>>("all")
  const [since, setSince] = useState("")
  const [until, setUntil] = useState("")
  const [error, setError] = useState("")
  return (
    <form
      aria-label="查询运行轨迹"
      className="surface-panel space-y-4 p-4"
      onSubmit={(event) => {
        event.preventDefault()
        const start = since ? new Date(since) : null
        const end = until ? new Date(until) : null
        if (
          [start, end].some(
            (value) => value && !Number.isFinite(value.getTime())
          )
        ) {
          setError("请输入有效的本地时间。")
          return
        }
        if (start && end && start > end) {
          setError("结束时间不能早于开始时间。")
          return
        }
        setError("")
        onQuery({
          status,
          ...(runId.trim() ? { run_id: runId.trim() } : {}),
          ...(start ? { since: start.toISOString() } : {}),
          ...(end ? { until: end.toISOString() } : {}),
        })
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <div className="space-y-2">
          <label htmlFor={`${id}-run`} className="text-sm font-medium">
            运行编号
          </label>
          <Input
            id={`${id}-run`}
            value={runId}
            onChange={(event) => setRunId(event.target.value)}
            pattern="[a-f0-9]{32}"
            placeholder="完整的 32 位运行编号"
            autoComplete="off"
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-status`} className="block text-sm font-medium">
            运行结果
          </label>
          <Select
            id={`${id}-status`}
            className="w-full"
            label="运行结果"
            value={status}
            onValueChange={setStatus}
            options={[
              { value: "all", label: "全部结果" },
              { value: "error", label: "发生错误" },
              { value: "interrupted", label: "上次运行未结束" },
              { value: "completed", label: "已完成" },
              { value: "running", label: "进行中" },
            ]}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-since`} className="text-sm font-medium">
            最后更新起始时间
          </label>
          <Input
            id={`${id}-since`}
            type="datetime-local"
            value={since}
            onChange={(event) => setSince(event.target.value)}
          />
        </div>
        <div className="space-y-2">
          <label htmlFor={`${id}-until`} className="text-sm font-medium">
            最后更新结束时间
          </label>
          <Input
            id={`${id}-until`}
            type="datetime-local"
            value={until}
            onChange={(event) => setUntil(event.target.value)}
          />
        </div>
      </div>
      <p className="text-xs text-muted-foreground">
        时间使用当前设备时区，按运行的最后更新筛选，包含起止边界。
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit">查询轨迹</Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => {
            setRunId("")
            setStatus("all")
            setSince("")
            setUntil("")
            setError("")
            onQuery({})
          }}
        >
          清空查询
        </Button>
      </div>
    </form>
  )
}
