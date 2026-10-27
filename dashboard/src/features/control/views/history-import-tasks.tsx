import { useCallback, useEffect, useState } from "react"
import { RefreshCw } from "lucide-react"
import { Badge, Button } from "@/ui"
import type { HistoryImportClient, ImportTask } from "../history-import-model"

const statusLabels: Record<ImportTask["status"], string> = {
  queued: "排队中",
  running: "处理中",
  interrupted: "已中断",
  completed: "已完成",
  partial: "部分完成",
  failed: "失败",
  cancelled: "已取消",
  abandoned: "已放弃",
}

function statusTone(
  status: ImportTask["status"]
): "success" | "warning" | "danger" | "info" {
  if (status === "completed") return "success"
  if (status === "failed" || status === "cancelled" || status === "abandoned")
    return "danger"
  if (status === "partial" || status === "interrupted") return "warning"
  return "info"
}

export function HistoryImportTasks({
  client,
  busy,
}: {
  client: HistoryImportClient
  busy: boolean
}) {
  const [tasks, setTasks] = useState<ImportTask[]>([])
  const [error, setError] = useState("")
  const [working, setWorking] = useState(false)
  const [taskAction, setTaskAction] = useState<{
    id: string
    action: "cancel" | "retry" | "abandon"
  } | null>(null)

  const refreshTasks = useCallback(async () => {
    try {
      setTasks(await client.importTasks())
      setError("")
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取任务失败")
    }
  }, [client])

  useEffect(() => {
    const initial = window.setTimeout(() => void refreshTasks(), 0)
    const timer = window.setInterval(() => void refreshTasks(), 3000)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [refreshTasks])

  async function runTaskAction() {
    if (!taskAction) return
    setWorking(true)
    setError("")
    try {
      if (taskAction.action === "cancel")
        await client.cancelImport(taskAction.id)
      else if (taskAction.action === "retry")
        await client.retryImport(taskAction.id)
      else await client.abandonImport(taskAction.id)
      setTaskAction(null)
      await refreshTasks()
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "任务操作失败")
    } finally {
      setWorking(false)
    }
  }

  const confirmText = taskAction
    ? {
        cancel: "取消只会停止尚未完成的历史提取，已经写入的记忆不会回滚。",
        retry:
          "系统会在保留期内使用相同文件和已确认的角色映射，从头重试；已提取消息会按稳定 ID 跳过。",
        abandon:
          "放弃后会删除保留文件，未完成的导入消息会进入失败隔离，之后无法从这个任务重试。",
      }[taskAction.action]
    : ""

  return (
    <section className="surface-panel space-y-4 p-5 sm:p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">导入任务</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            任务进度每 3 秒刷新。摘要不保存聊天正文和用户 ID。
          </p>
        </div>
        <Button variant="outline" onClick={() => void refreshTasks()}>
          <RefreshCw className="size-4" />
          立即刷新
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      {tasks.length === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          暂无历史导入任务。
        </p>
      ) : (
        <ul className="space-y-3">
          {tasks.map((task) => {
            const processed = task.extractedCount + task.failedCount
            let progress = 0
            if (task.sourceCount) {
              progress = Math.min(
                100,
                Math.round((processed / task.sourceCount) * 100)
              )
            } else if (task.status === "completed") {
              progress = 100
            }
            return (
              <li key={task.id} className="rounded-xl border p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono text-xs">{task.id}</span>
                    <Badge tone={statusTone(task.status)}>
                      {statusLabels[task.status]}
                    </Badge>
                    {task.personaStatus !== "pending" && (
                      <Badge variant="outline">
                        人格：{task.personaStatus}
                      </Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {task.createdAt}
                  </span>
                </div>
                <div className="mt-4 grid gap-3 text-sm sm:grid-cols-4">
                  <div>
                    <span className="text-muted-foreground">Source</span>
                    <p>{task.sourceCount}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">待提取</span>
                    <p>{task.pendingCount}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">已提取</span>
                    <p>{task.extractedCount}</p>
                  </div>
                  <div>
                    <span className="text-muted-foreground">
                      失败 / 重复 / 跳过
                    </span>
                    <p>
                      {task.failedCount} / {task.duplicateCount} /{" "}
                      {task.skippedCount}
                    </p>
                  </div>
                </div>
                <div
                  className="mt-3 h-2 overflow-hidden rounded-full bg-muted"
                  role="progressbar"
                  aria-label={`任务 ${task.id} 提取进度`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={progress}
                >
                  <div
                    className="h-full rounded-full bg-primary transition-[width]"
                    style={{ width: `${progress}%` }}
                  />
                </div>
                {task.errorTypes.length > 0 && (
                  <p className="mt-3 text-xs text-destructive">
                    错误类型：{task.errorTypes.join("、")}
                  </p>
                )}
                <div className="mt-4 flex flex-wrap gap-2">
                  {(task.status === "queued" || task.status === "running") && (
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={working}
                      onClick={() =>
                        setTaskAction({ id: task.id, action: "cancel" })
                      }
                    >
                      取消
                    </Button>
                  )}
                  {task.canRetry && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={working || busy}
                      onClick={() =>
                        setTaskAction({ id: task.id, action: "retry" })
                      }
                    >
                      重试
                    </Button>
                  )}
                  {(task.status === "interrupted" ||
                    task.status === "failed" ||
                    task.status === "partial") && (
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={working}
                      onClick={() =>
                        setTaskAction({ id: task.id, action: "abandon" })
                      }
                    >
                      放弃并清理文件
                    </Button>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
      {taskAction && (
        <div className="rounded-xl border border-warning/30 bg-warning-soft p-4">
          <p className="text-sm leading-6">{confirmText}</p>
          <div className="mt-3 flex gap-2">
            <Button
              size="sm"
              variant="destructive"
              disabled={working}
              onClick={() => void runTaskAction()}
            >
              确认操作
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={working}
              onClick={() => setTaskAction(null)}
            >
              返回
            </Button>
          </div>
        </div>
      )}
    </section>
  )
}
