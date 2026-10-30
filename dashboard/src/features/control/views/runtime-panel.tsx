import { Badge, Button, JsonView } from "@/ui"
import type { ManagementClient, RuntimeStatus } from "../model"
import { PersonaEvidence } from "./persona-evidence"

function toneForCapacity(state: string): "success" | "warning" | "info" {
  if (state === "normal") return "success"
  if (state === "protective") return "warning"
  return "info"
}

export function RuntimePanel({
  status,
  busy,
  onAction,
  client,
}: {
  status: RuntimeStatus | null
  busy: boolean
  onAction: (action: "extract" | "weekly" | "cancel") => void
  client: ManagementClient
}) {
  const task = status?.activeTask
  const policy = status?.extractionPolicy
  const capacity = status?.capacity
  const persona = status?.persona
  const maintenanceAvailable = status?.capabilities?.maintenanceTasks !== false
  return (
    <section className="mx-auto w-full max-w-6xl space-y-6 p-5 sm:p-8">
      <div className="workspace-intro">
        <h1 className="text-2xl font-semibold">运行检测与任务</h1>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ["定时任务", String(status?.schedulerCount ?? "—")],
          [
            "待抽取消息",
            maintenanceAvailable
              ? String(
                  status?.pending.reduce(
                    (total, item) => total + item.count,
                    0
                  ) ?? "—"
                )
              : "—",
          ],
          ["当前操作", task?.kind ?? "空闲"],
          ["待提交强化记忆", String(status?.checkpointPending ?? "—")],
        ].map(([label, value]) => (
          <div key={label} className="surface-panel p-6">
            <p className="text-xs text-muted-foreground">{label}</p>
            <p className="mt-3 text-2xl font-semibold">{value}</p>
          </div>
        ))}
      </div>
      {capacity && (
        <section className="surface-panel space-y-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">容量治理</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                压力 {Math.round(capacity.pressure * 100)}% · 队列{" "}
                {capacity.queue["pending"] ?? 0} 待抽取 ·{" "}
                {capacity.queue["deferred"] ?? 0} 延迟 ·{" "}
                {capacity.queue["dead"] ?? 0} 失败隔离
              </p>
            </div>
            <Badge tone={toneForCapacity(capacity.state)}>
              {capacity.state}
            </Badge>
          </div>
          <dl className="grid gap-4 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-muted-foreground">待抽取</dt>
              <dd>{capacity.snapshot.pendingRows}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">延迟写入</dt>
              <dd>{capacity.snapshot.deferredRows}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">失败隔离</dt>
              <dd>{capacity.snapshot.deadRows}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">数据库</dt>
              <dd>
                {Math.round(capacity.snapshot.databaseBytes / 1024 / 1024)} MB
              </dd>
            </div>
          </dl>
        </section>
      )}
      {persona && (
        <section className="surface-panel space-y-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold">人格时间线</h2>
              <p className="mt-1 text-xs text-muted-foreground">
                当前第 {persona.revision} 版
              </p>
            </div>
            <Badge tone="info">{persona.id}</Badge>
          </div>
          <p className="text-sm leading-6">{persona.text || "暂无人格文本"}</p>
          <ol className="space-y-3 text-sm">
            {persona.revisions.map((revision) => (
              <li key={revision.revision} className="border-l pl-3">
                <div className="flex flex-wrap justify-between gap-2 text-xs text-muted-foreground">
                  <span>
                    r{revision.revision} · {revision.op}
                  </span>
                  <span>{revision.at}</span>
                </div>
                <p className="mt-1 leading-6">{revision.text}</p>
              </li>
            ))}
          </ol>
          <PersonaEvidence client={client} persona={persona} />
        </section>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {status?.checks.map((check) => (
          <div
            key={check.name}
            className="surface-panel flex items-center justify-between gap-3 p-5"
          >
            <div>
              <p className="font-medium">
                {{
                  engine: "记忆引擎",
                  journal: "生命周期日志",
                  ledger: "账本哈希链",
                  provider: "模型配置",
                }[check.name] ?? check.name}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {check.detail}
              </p>
            </div>
            <Badge tone={check.ok ? "success" : "warning"}>
              {check.ok ? "正常" : "需检查"}
            </Badge>
          </div>
        ))}
      </div>
      <div className="surface-panel space-y-4 p-6">
        <h2 className="text-lg font-semibold">维护操作</h2>
        <p className="text-sm leading-6 text-muted-foreground">
          {maintenanceAvailable
            ? "立即抽取会调用配置的模型并写入记忆；每周整理会遗忘、合并并提炼人格。操作共用后台任务锁，运行期间暂停人工编辑。"
            : "独立控制台未启用模型与后台维护任务。你仍可查看和编辑记忆、管理人格包。"}
        </p>
        <div className="flex flex-wrap gap-3">
          <Button
            disabled={busy || !!task || !status?.ready || !maintenanceAvailable}
            onClick={() => {
              onAction("extract")
            }}
          >
            立即抽取
          </Button>
          <Button
            variant="outline"
            disabled={busy || !!task || !status?.ready || !maintenanceAvailable}
            onClick={() => {
              onAction("weekly")
            }}
          >
            运行每周整理
          </Button>
          {task && (
            <Button
              variant="destructive"
              onClick={() => {
                onAction("cancel")
              }}
            >
              取消当前任务
            </Button>
          )}
        </div>
        {task && (
          <p className="font-mono text-xs wrap-anywhere">
            任务 ID：{task.id} · 每 2 秒刷新
          </p>
        )}
      </div>
      {policy && maintenanceAvailable && (
        <section className="surface-panel space-y-3 p-6">
          <h2 className="font-semibold">抽取策略</h2>
          <dl className="grid gap-4 text-sm sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">积压触发阈值</dt>
              <dd>
                {policy.backlogThreshold > 0
                  ? `${policy.backlogThreshold} 条消息`
                  : "已关闭"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">话题 TTL</dt>
              <dd>
                {policy.topicTtlSeconds > 0
                  ? `${policy.topicTtlSeconds / 3600} 小时`
                  : "已关闭"}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground">每批话题上限</dt>
              <dd>{policy.maxTopicsPerBatch} 个</dd>
            </div>
          </dl>
          <p className="text-xs leading-6 text-muted-foreground">
            积压触发需等待安静窗口；话题超期会触发抽取，不会自动删除消息。策略由后端执行，实际抽取仍需可用模型。
            待提交强化表示尚未通过 checkpoint 持久化的记忆数量，不是抽取队列。
          </p>
        </section>
      )}
      {maintenanceAvailable && (
        <>
          <section className="surface-panel space-y-4 p-6">
            <h2 className="font-semibold">
              待抽取话题 · {status?.pendingTopics.length ?? "—"}
            </h2>
            {!status && (
              <p className="text-sm text-muted-foreground">暂无运行数据。</p>
            )}
            {status?.pendingTopics.length === 0 && (
              <p className="text-sm text-muted-foreground">
                没有待抽取的话题。
              </p>
            )}
            <ul className="divide-y">
              {status?.pendingTopics.map((topic) => (
                <li
                  key={`${topic.session}:${topic.id}`}
                  className="space-y-2 py-3"
                >
                  <div className="flex items-start justify-between gap-3">
                    <code className="text-xs wrap-anywhere">{topic.id}</code>
                    <Badge variant="outline">{topic.count} 条消息</Badge>
                  </div>
                  <p className="text-xs wrap-anywhere text-muted-foreground">
                    会话：{topic.session}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    最早消息：{topic.oldestAt ?? "时间未记录"}
                  </p>
                </li>
              ))}
            </ul>
          </section>
          <div className="grid gap-6 lg:grid-cols-2">
            <section className="space-y-3">
              <h2 className="font-semibold">会话汇总</h2>
              <ul className="space-y-2 text-sm">
                {status?.pending.map((item) => (
                  <li key={item.session} className="flex justify-between gap-3">
                    <span className="wrap-anywhere">{item.session}</span>
                    <span className="shrink-0">{item.count} 条</span>
                  </li>
                ))}
              </ul>
            </section>
            <section className="space-y-3">
              <h2 className="font-semibold">当前配置</h2>
              <p className="text-xs text-muted-foreground">
                配置编辑使用 AstrBot
                插件配置页。此处展示实际配置，不代表所有历史配置项均已接入执行路径。
              </p>
              <JsonView value={status?.config ?? {}} />
            </section>
          </div>
        </>
      )}
    </section>
  )
}
