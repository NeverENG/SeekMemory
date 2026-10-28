import { useRef, useState } from "react"
import { Button, Input } from "@/ui"
import type { PersonaBundle } from "@/features/shell/model"
import { readArtwork } from "../pack-file"

export function PackImport({
  pack,
  setPack,
  expectedVersion,
  setExpectedVersion,
  busy,
  onSave,
  onCancel,
}: {
  pack: PersonaBundle
  setPack: (value: PersonaBundle) => void
  expectedVersion: string
  setExpectedVersion: (value: string) => void
  busy: boolean
  onSave: () => void
  onCancel: () => void
}) {
  const [error, setError] = useState("")
  const [reading, setReading] = useState(false)
  const request = useRef(0)
  return (
    <section
      className="console-panel my-5 space-y-4 p-6"
      aria-label="确认人格包导入"
    >
      <h2>
        确认导入：{pack.seed.name} · v{pack.seed.version}
      </h2>
      <p className="text-sm text-muted-foreground">
        {pack.seed.persona.slice(0, 160)}
      </p>
      <div className="flex flex-wrap gap-3 text-sm">
        <span>许可证：{pack.seed.license || "未声明"}</span>
        <span>来源：{pack.seed.source || "未声明"}</span>
        <span>
          分级：
          {pack.seed.content_rating === "general"
            ? "全年龄"
            : pack.seed.content_rating || "未分级"}
        </span>
      </div>
      {pack.artwork && (
        <img
          className="max-h-48 max-w-full rounded-xl object-contain"
          src={`data:image/png;base64,${pack.artwork.dataBase64}`}
          alt="待导入封面"
        />
      )}
      <div className="flex flex-wrap items-center gap-3">
        <label className="console-upload">
          {pack.artwork ? "更换封面" : "添加封面（可选）"}
          <input
            type="file"
            accept=".png,image/png"
            disabled={busy || reading}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ""
              if (!file) return
              const version = ++request.current
              setReading(true)
              setError("")
              void readArtwork(file)
                .then((artwork) => {
                  if (version === request.current) setPack({ ...pack, artwork })
                })
                .catch((e: unknown) =>
                  setError(e instanceof Error ? e.message : "图片无效")
                )
                .finally(() => setReading(false))
            }}
          />
        </label>
        {pack.artwork && (
          <Button
            variant="ghost"
            disabled={busy || reading}
            onClick={() => setPack({ ...pack, artwork: null })}
          >
            移除封面
          </Button>
        )}
        <span className="text-xs text-muted-foreground">
          静态 PNG，最大 2 MiB、2048×2048。
        </span>
      </div>
      <label className="block space-y-2 text-sm">
        许可证正文{pack.artwork ? "（封面需包含在授权范围内）" : "（可选）"}
        <textarea
          aria-label="人格包许可证正文"
          className="min-h-28 w-full rounded-xl border bg-background p-3"
          maxLength={65536}
          disabled={busy || reading}
          value={pack.licenseText}
          onChange={(e) => setPack({ ...pack, licenseText: e.target.value })}
        />
      </label>
      <Input
        aria-label="被更新人格包的旧版本"
        placeholder="新增包留空；更新请填写旧版本号"
        value={expectedVersion}
        disabled={busy || reading}
        onChange={(e) => setExpectedVersion(e.target.value)}
      />
      <p className="text-xs text-muted-foreground">
        仅保存蓝图，不会自动安装；更新保留旧包备份。
      </p>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button
          disabled={
            busy ||
            reading ||
            (!!pack.artwork &&
              (!pack.licenseText.trim() ||
                !pack.seed.license?.trim() ||
                !pack.seed.source?.trim()))
          }
          onClick={onSave}
        >
          {reading ? "读取图片中…" : "确认保存蓝图"}
        </Button>
        <Button variant="ghost" disabled={busy || reading} onClick={onCancel}>
          取消
        </Button>
      </div>
      {!!pack.artwork &&
        (!pack.seed.license?.trim() || !pack.seed.source?.trim()) && (
          <p role="alert" className="text-sm text-destructive">
            设定未声明许可证或来源，请先补全 JSON 中的 license 和
            source，或移除封面。
          </p>
        )}
    </section>
  )
}
