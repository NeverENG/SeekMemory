import { useEffect, useRef, useState } from "react"
import { Button, JsonView } from "@/ui"
import type { ConsoleClient, PersonaBundle } from "@/features/shell/model"
import { PersonaFields } from "@/features/persona/views/persona-fields"
import type { FieldErrors } from "@/features/persona/settings"
import {
  copyPack,
  nextVersion,
  packErrors,
  validatePack,
  type PackDraft,
  type PackLookup,
} from "../authoring"
import { useArtworkImport } from "../use-artwork-import"
import { PackMetadataFields } from "./pack-metadata-fields"

export function PackEditor({
  initial,
  client,
  blocked,
  onSaved,
  onCancel,
}: {
  initial: PackDraft
  client: ConsoleClient
  blocked: boolean
  onSaved: () => Promise<void>
  onCancel: () => void
}) {
  const [pack, setPack] = useState<PersonaBundle>(initial.pack)
  const [target, setTarget] = useState<{
    reference: string
    result: PackLookup
  } | null>(null)
  const [errors, setErrors] = useState<FieldErrors>({})
  const [error, setError] = useState("")
  const [busy, setBusy] = useState(false)
  const [reviewRequired, setReviewRequired] = useState(false)
  const [reloading, setReloading] = useState(false)
  const acting = useRef(false)
  const reference = `mine/${pack.seed.id}`
  const validId = /^[a-z0-9][a-z0-9._-]{1,63}$/.test(pack.seed.id)
  const upload = useArtworkImport((artwork) =>
    setPack((current) => ({ ...current, artwork }))
  )
  useEffect(() => {
    let active = true
    if (!validId) return
    const originalRef = `mine/${initial.pack.seed.id}`
    const read =
      initial.target && reference === originalRef
        ? Promise.resolve(initial.target)
        : client.packLookup(reference)
    void read
      .then((result) => {
        if (active) {
          setTarget({ reference, result })
          setError("")
        }
      })
      .catch(() => {
        if (active)
          setError("无法核对已保存包，请重试；未能确认目标时不会保存。")
      })
    return () => {
      active = false
    }
  }, [client, pack.seed.id, reference, initial, validId])
  const lookup = target?.reference === reference ? target.result : null
  const save = async () => {
    if (
      acting.current ||
      blocked ||
      !lookup ||
      reviewRequired ||
      upload.reading
    )
      return
    const result = validatePack(pack, lookup)
    setErrors(result.success ? {} : packErrors(result.error))
    if (!result.success) return
    acting.current = true
    setBusy(true)
    setError("")
    try {
      await client.persona({
        operation: "importPack",
        pack: result.data,
        confirmed: true,
        ...(lookup.pack
          ? {
              expectedVersion: lookup.pack.seed.version,
              expectedDigest: lookup.digest,
            }
          : {}),
      })
      await onSaved()
      onCancel()
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "保存失败，请重新加载已保存包后核对"
      )
      setReviewRequired(true)
    } finally {
      acting.current = false
      setBusy(false)
    }
  }
  const reload = async () => {
    if (acting.current) return
    acting.current = true
    setReloading(true)
    try {
      const result = await client.packLookup(reference)
      setTarget({ reference, result })
      if (result.pack)
        setPack({
          ...result.pack,
          seed: {
            ...result.pack.seed,
            version: nextVersion(result.pack.seed.version),
          },
        })
      setReviewRequired(false)
      setError("")
      setErrors({})
    } catch {
      setError("重新加载失败，请检查连接后重试。")
    } finally {
      acting.current = false
      setReloading(false)
    }
  }
  let saveLabel = "保存新包"
  if (lookup?.pack) saveLabel = "保存包更新"
  if (busy) saveLabel = "保存中…"
  return (
    <section
      className="console-panel my-5 min-w-0 p-5 sm:p-6"
      aria-label="人格包编辑器"
    >
      <form
        className="mx-auto max-w-2xl space-y-5"
        onSubmit={(e) => {
          e.preventDefault()
          void save()
        }}
      >
        <h2 className="text-xl font-semibold">{initial.title}</h2>
        <p className="text-sm text-muted-foreground">
          保存的是可重复使用的蓝图。保存后可到预览中应用到当前人格。
        </p>
        <fieldset
          disabled={busy || reloading || reviewRequired}
          className="min-w-0 space-y-5"
        >
          <legend className="sr-only">人格包内容</legend>
          <PersonaFields
            value={{
              name: pack.seed.name,
              persona: pack.seed.persona,
              style: pack.seed.style ?? {},
              boundaries: pack.seed.boundaries ?? [],
            }}
            onChange={(settings) =>
              setPack({ ...pack, seed: { ...pack.seed, ...settings } })
            }
            errors={errors}
          />
          <PackMetadataFields
            pack={pack}
            onChange={setPack}
            errors={{
              ...errors,
              ...(!validId
                ? { id: "包标识需为 2–64 位小写字母、数字、点、下划线或短横线" }
                : {}),
            }}
          />
          <section className="space-y-3" aria-label="包封面">
            <h3 className="font-semibold">封面</h3>
            {pack.artwork && (
              <img
                className="max-h-48 max-w-full rounded-xl object-contain"
                src={`data:image/png;base64,${pack.artwork.dataBase64}`}
                alt="待保存的封面"
              />
            )}
            <label className="console-upload">
              {pack.artwork ? "更换封面" : "添加封面"}
              <input
                type="file"
                accept=".png,image/png"
                disabled={upload.reading}
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  e.target.value = ""
                  if (file) void upload.readFile(file)
                }}
              />
            </label>
            {pack.artwork && (
              <Button
                type="button"
                variant="ghost"
                disabled={upload.reading}
                onClick={() => setPack({ ...pack, artwork: null })}
              >
                移除封面
              </Button>
            )}
            <p className="text-xs text-muted-foreground">
              静态 PNG，最大 2 MiB、2048×2048；需声明来源与包含封面的许可证。
            </p>
            {(upload.error || errors["artwork"]) && (
              <p role="alert" className="text-sm text-destructive">
                {upload.error || errors["artwork"]}
              </p>
            )}
          </section>
          <details>
            <summary>查看将保留的完整包数据</summary>
            <p className="text-sm text-muted-foreground">
              已有创作样例与其他受支持设定均完整保留。
            </p>
            <JsonView value={pack} />
          </details>
        </fieldset>
        {errors["form"] && (
          <p role="alert" className="text-sm text-destructive">
            {errors["form"]}
          </p>
        )}
        {lookup ? (
          <p role="status" className="text-sm">
            {lookup.pack
              ? `将更新我的包「${lookup.pack.seed.name}」，已保存版本 ${lookup.pack.seed.version}。旧包会保留备份。`
              : "将创建新的个人包。"}
          </p>
        ) : (
          <p role="status" className="text-sm">
            {validId ? "正在核对已保存包…" : "请先修正包标识。"}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {(reviewRequired || (error && !lookup)) && (
          <Button
            type="button"
            variant="outline"
            disabled={reloading}
            onClick={() => {
              void reload()
            }}
          >
            重新载入已保存包并核对（替换草稿）
          </Button>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            type="submit"
            disabled={
              blocked ||
              busy ||
              reloading ||
              reviewRequired ||
              upload.reading ||
              !lookup
            }
          >
            {saveLabel}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={busy || reloading || upload.reading}
            onClick={() => {
              setPack(copyPack(pack))
              setTarget(null)
              setErrors({})
              setError("")
              setReviewRequired(false)
            }}
          >
            另存为新包
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={busy || reloading}
            onClick={onCancel}
          >
            取消
          </Button>
        </div>
      </form>
    </section>
  )
}
