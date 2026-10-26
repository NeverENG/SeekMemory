import { useState } from "react"
import { Button, Input } from "@/ui"
import type { HistoryImportClient } from "../history-import-model"
import type { ChatLabPreview, ChatLabUpload } from "../history-import-model"
import { HistoryImportPreview } from "./history-import-preview"
import { HistoryImportTasks } from "./history-import-tasks"

export function HistoryImport({
  client,
  busy,
}: {
  client: HistoryImportClient
  busy: boolean
}) {
  const [upload, setUpload] = useState<ChatLabUpload | null>(null)
  const [validated, setValidated] = useState<ChatLabPreview | null>(null)
  const [botMemberId, setBotMemberId] = useState("")
  const [targetMemberId, setTargetMemberId] = useState("")
  const [targetUmo, setTargetUmo] = useState("")
  const [confirmChecked, setConfirmChecked] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const [working, setWorking] = useState(false)

  function clearValidation() {
    setValidated(null)
    setConfirmChecked(false)
  }

  async function uploadFile(file: File | undefined) {
    if (!file) return
    setWorking(true)
    setError("")
    setNotice("")
    setUpload(null)
    clearValidation()
    setBotMemberId("")
    setTargetMemberId("")
    setTargetUmo("")
    try {
      setUpload(await client.uploadImport(file))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "上传或检查文件失败")
    } finally {
      setWorking(false)
    }
  }

  function roleCommand() {
    if (!upload) throw new Error("请先上传文件")
    if (!botMemberId || !targetMemberId || botMemberId === targetMemberId)
      throw new Error("请选择两个不同的文件成员，分别作为 Bot 和目标用户")
    if (
      !targetUmo.includes(":FriendMessage:") ||
      targetUmo.includes("GroupMessage")
    )
      throw new Error(
        "请填写 AstrBot 私聊 UMO，例如 platform:FriendMessage:user-id"
      )
    return {
      stageKey: upload.stageKey,
      botPlatformId: botMemberId,
      targetPlatformId: targetMemberId,
      botMemberId,
      targetMemberId,
      targetUmo: targetUmo.trim(),
    }
  }

  async function validate() {
    setWorking(true)
    setError("")
    setNotice("")
    clearValidation()
    try {
      const result = await client.validateImport(roleCommand())
      setValidated(result)
      setNotice("预检完成。此步骤尚未写入正式 Source。")
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "预检失败")
    } finally {
      setWorking(false)
    }
  }

  async function confirmImport() {
    if (!validated) return
    setWorking(true)
    setError("")
    setNotice("")
    try {
      const id = await client.confirmImport({
        ...roleCommand(),
        confirmed: true,
      })
      setNotice(`初始化任务 ${id} 已提交。`)
      setUpload(null)
      setValidated(null)
      setConfirmChecked(false)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建导入任务失败")
    } finally {
      setWorking(false)
    }
  }

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 p-5 sm:p-8">
      <header className="workspace-intro">
        <h1 className="text-2xl font-semibold">历史私聊初始化</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
          管理员上传一份 ChatLab v0.0.2 私聊文件，确认 Bot 与目标用户后，将 Bot
          行为证据沉淀为共享人格，并把互动记忆归入该用户。首版临时上限：JSON 20
          MiB / 10 万条，JSONL 512 MiB / 200 万条。
        </p>
      </header>

      <section className="surface-panel space-y-5 p-5 sm:p-6">
        <div>
          <h2 className="text-lg font-semibold">上传并预检</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            一次只处理一个 Bot
            与一个用户的私聊。预览只显示元数据，不展示消息正文。
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label
            htmlFor="history-import-file"
            className="grid min-w-64 flex-1 gap-2 text-sm"
          >
            选择 ChatLab JSON / JSONL 文件
            <Input
              id="history-import-file"
              type="file"
              accept=".json,.jsonl,application/json"
              disabled={working}
              onChange={(event) => void uploadFile(event.target.files?.[0])}
            />
          </label>
        </div>
        {upload && (
          <div className="space-y-5 border-t pt-5">
            <HistoryImportPreview
              upload={upload}
              botMemberId={botMemberId}
              targetMemberId={targetMemberId}
              targetUmo={targetUmo}
              onBotMemberChange={(value) => {
                setBotMemberId(value)
                clearValidation()
              }}
              onTargetMemberChange={(value) => {
                setTargetMemberId(value)
                clearValidation()
              }}
              onTargetUmoChange={(value) => {
                setTargetUmo(value)
                clearValidation()
              }}
            />
            <div className="flex flex-wrap items-center gap-3">
              <Button
                disabled={working || busy}
                onClick={() => void validate()}
              >
                预检角色与稳定 ID
              </Button>
              {busy && (
                <span className="text-xs text-muted-foreground">
                  当前有维护任务，提交会暂不可用。
                </span>
              )}
            </div>
            {validated && (
              <div className="space-y-4 rounded-xl border border-primary/25 bg-primary/5 p-4">
                <h3 className="font-medium">预检结果</h3>
                <p className="text-sm leading-6">
                  将创建 {validated.uniqueSourceCount ?? 0} 条新 Source，跳过{" "}
                  {validated.duplicateCount ?? 0} 条重复消息；文件内无效行{" "}
                  {validated.skippedCount} 条。
                </p>
                <label className="flex items-start gap-2 text-sm leading-6">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={confirmChecked}
                    onChange={(event) =>
                      setConfirmChecked(event.target.checked)
                    }
                  />
                  我已核对 Bot 成员、目标用户、私聊 UMO
                  和跳过数量；确认后会写入不可变 Source 并开始模型提取。
                </label>
                <Button
                  disabled={!confirmChecked || working || busy}
                  onClick={() => void confirmImport()}
                >
                  确认并开始初始化
                </Button>
              </div>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {notice && (
          <p role="status" className="text-sm text-success">
            {notice}
          </p>
        )}
      </section>

      <HistoryImportTasks client={client} busy={busy} />
    </main>
  )
}
