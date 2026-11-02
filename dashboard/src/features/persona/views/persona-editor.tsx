import { useCallback, useId, useRef, useState } from "react"
import { Button, DetailDrawer, Input } from "@/ui"
import type { ManagementClient } from "@/features/control/model"
import { useResource } from "@/features/shell/use-resource"
import { ResourceState } from "@/features/shell/page-parts"
import {
  editedPayload,
  fieldErrors,
  settingsFromDetail,
  settingsSchema,
  type FieldErrors,
  type PersonaSettings,
} from "../settings"
import { PersonaFields } from "./persona-fields"

export function PersonaEditor({
  client,
  id,
  blocked,
  onClose,
  onSaved,
}: {
  client: ManagementClient
  id: string
  blocked: boolean
  onClose: () => void
  onSaved: () => Promise<void>
}) {
  const reasonId = useId()
  const [draft, setDraft] = useState<PersonaSettings | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [reason, setReason] = useState("")
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [reviewRequired, setReviewRequired] = useState(false)
  const acting = useRef(false)
  const read = useCallback(async () => {
    const detail = await client.detail(id)
    setDraft(settingsFromDetail(detail))
    setErrors({})
    setError("")
    setReviewRequired(false)
    return detail
  }, [client, id])
  const vm = useResource(read)
  const save = async () => {
    if (!draft || !vm.data || acting.current || blocked || reviewRequired)
      return
    const result = settingsSchema.safeParse(draft)
    setErrors(result.success ? {} : fieldErrors(result.error))
    if (!result.success || !reason.trim()) return
    acting.current = true
    setBusy(true)
    setError("")
    try {
      const { header } = vm.data.artifact
      await client.update({
        id,
        expectedRevision: header.revision,
        payload: editedPayload(vm.data, result.data),
        scope: header.scope,
        state: header.state,
        reason,
        confirmed: true,
      })
      await onSaved()
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败，请重新加载后核对")
      setReviewRequired(true)
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  return (
    <DetailDrawer
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
      title="编辑当前人格"
      description="修改当前人格设定并保留历史"
    >
      <form
        className="space-y-5 p-6"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <h2 className="text-xl font-semibold">编辑当前人格</h2>
        <ResourceState
          loading={vm.loading}
          error={vm.error}
          onRetry={vm.reload}
        />
        {!vm.loading && draft && (
          <PersonaFields
            value={draft}
            onChange={setDraft}
            errors={errors}
            disabled={busy || reviewRequired}
          />
        )}
        <label htmlFor={reasonId} className="block space-y-2">
          <span>修改原因</span>
          <Input
            id={reasonId}
            value={reason}
            maxLength={300}
            disabled={busy}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
        <p className="text-sm text-muted-foreground">
          保存会修改当前人格，并在同一人格上新增版本。历史与来源记录保留。
        </p>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {reviewRequired && (
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              void vm.reload()
            }}
          >
            重新加载当前人格并核对（替换草稿）
          </Button>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            disabled={
              busy ||
              blocked ||
              reviewRequired ||
              vm.loading ||
              !draft ||
              !reason.trim()
            }
          >
            {busy ? "保存中…" : "保存当前人格的新版本"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy}
            onClick={onClose}
          >
            取消
          </Button>
        </div>
      </form>
    </DetailDrawer>
  )
}
