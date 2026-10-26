import { FileUp } from "lucide-react"
import { Badge, Input } from "@/ui"
import type { ChatLabUpload } from "../history-import-model"

function formatBytes(bytes: number): string {
  return `${(bytes / 1024 / 1024).toFixed(1)} MiB`
}

export function HistoryImportPreview({
  upload,
  botMemberId,
  targetMemberId,
  targetUmo,
  onBotMemberChange,
  onTargetMemberChange,
  onTargetUmoChange,
}: {
  upload: ChatLabUpload
  botMemberId: string
  targetMemberId: string
  targetUmo: string
  onBotMemberChange: (value: string) => void
  onTargetMemberChange: (value: string) => void
  onTargetUmoChange: (value: string) => void
}) {
  const { preview } = upload
  const rows = [
    ["会话", preview.name],
    ["格式", `ChatLab v${preview.version} · ${preview.format.toUpperCase()}`],
    ["平台", preview.platform],
    ["有效消息", `${preview.messageCount} 条`],
    ["无效行", `${preview.skippedCount} 条`],
    ["时间范围", `${preview.firstAt || "未知"} 至 ${preview.lastAt || "未知"}`],
  ] as const

  return (
    <div className="space-y-5 border-t pt-5">
      <div className="flex flex-wrap items-center gap-3">
        <FileUp className="size-5 text-primary" />
        <span className="font-medium">{upload.filename}</span>
        <Badge tone="info">{formatBytes(upload.size)}</Badge>
      </div>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([label, value]) => (
          <div key={label} className="rounded-lg border p-3">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 text-sm break-all">{value}</dd>
          </div>
        ))}
      </dl>
      {Object.keys(preview.senderCounts).length > 0 && (
        <div>
          <h3 className="text-sm font-medium">文件发言者与消息行数</h3>
          <ul className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(preview.senderCounts).map(([id, count]) => {
              const member = preview.members.find(
                (item) => item.platformId === id
              )
              return (
                <li key={id} className="rounded-lg border p-3">
                  <span className="font-mono break-all">{id}</span>
                  {member?.accountName && <span> · {member.accountName}</span>}
                  <span className="text-muted-foreground"> · {count} 条</span>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="grid gap-2 text-sm">
          Bot 成员（按平台 ID 确认）
          <select
            className="filter-select"
            value={botMemberId}
            onChange={(event) => onBotMemberChange(event.target.value)}
          >
            <option value="">请选择 Bot 成员</option>
            {preview.members.map((member) => (
              <option key={member.platformId} value={member.platformId}>
                {(member.accountName ? `${member.accountName} · ` : "") +
                  member.platformId}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-2 text-sm">
          目标用户成员（按平台 ID 确认）
          <select
            className="filter-select"
            value={targetMemberId}
            onChange={(event) => onTargetMemberChange(event.target.value)}
          >
            <option value="">请选择目标用户</option>
            {preview.members.map((member) => (
              <option key={member.platformId} value={member.platformId}>
                {(member.accountName ? `${member.accountName} · ` : "") +
                  member.platformId}
              </option>
            ))}
          </select>
        </label>
        <label
          htmlFor="history-import-umo"
          className="grid gap-2 text-sm sm:col-span-2"
        >
          目标私聊 UMO
          <Input
            id="history-import-umo"
            value={targetUmo}
            maxLength={300}
            placeholder="platform:FriendMessage:user-id"
            onChange={(event) => onTargetUmoChange(event.target.value)}
          />
          <span className="text-xs text-muted-foreground">
            UMO 中的用户 ID 必须与上方选择的目标成员 ID
            一致。昵称不用于角色判断， 导入内容只会进入该 UMO。
          </span>
        </label>
      </div>
      {preview.warnings.length > 0 && (
        <div className="rounded-lg border border-warning/30 bg-warning-soft p-4">
          <h3 className="text-sm font-medium">
            可隔离的问题行（最多展示 50 条）
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            预览已统计 {preview.skippedCount}{" "}
            条无效行；确认后会跳过这些行，任务将标记为部分完成。
          </p>
          <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {preview.warnings.slice(0, 50).map((warning, index) => (
              <li key={`${warning.row}-${index}`}>
                第 {warning.row} 行：{warning.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
