import { useState } from "react"
import { Button, DetailDrawer } from "@/ui"
import { downloadPack } from "../pack-file"
import { PackArtwork } from "./pack-artwork"
import { SettingsComparison } from "@/features/persona/views/settings-comparison"
import { settingsFromDetail } from "@/features/persona/settings"
import type {
  ConsoleClient,
  PersonaPack,
  PersonaSeed,
} from "@/features/shell/model"
import type { ArtifactDetail } from "@/features/control/model"

export function PackPreview({
  client,
  selected,
  seed,
  current,
  licenseText,
  error,
  busy,
  blocked,
  confirmed,
  setConfirmed,
  reviewRequired,
  onClose,
  onInstall,
  onRemove,
  onExport,
  onEdit,
  onReload,
}: {
  client: ConsoleClient
  selected: PersonaPack | null
  seed: PersonaSeed | null
  current: ArtifactDetail | null
  licenseText: string
  error: string
  busy: boolean
  blocked: boolean
  confirmed: boolean
  setConfirmed: (value: boolean) => void
  reviewRequired: boolean
  onClose: () => void
  onInstall: () => void
  onRemove: () => void
  onExport: () => void
  onEdit: () => void
  onReload: () => void
}) {
  const [removeConfirmed, setRemoveConfirmed] = useState(false)
  return (
    <DetailDrawer
      open={!!selected}
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
      title={selected?.name ?? "人格包预览"}
      description="比较当前与目标设定，确认后应用"
    >
      <div className="space-y-5 p-6">
        <h2 className="text-xl font-semibold">{selected?.name}</h2>
        {!seed && !error && <p role="status">正在读取人格与当前设定…</p>}
        {seed && selected && (
          <>
            <div className="seed-art seed-art-neutral">
              <PackArtwork pack={selected} client={client} />
            </div>
            <p className="text-sm text-muted-foreground">
              包版本 {seed.version} · 许可证：{seed.license || "未声明"} ·
              来源：{seed.source || "未声明"}
            </p>
            <SettingsComparison
              before={current ? settingsFromDetail(current) : null}
              after={{
                name: seed.name,
                persona: seed.persona,
                style: seed.style ?? {},
                boundaries: seed.boundaries ?? [],
              }}
            />
            {!!licenseText && (
              <details>
                <summary>许可证正文</summary>
                <p className="wrap-anywhere whitespace-pre-wrap">
                  {licenseText}
                </p>
              </details>
            )}
            {!!seed.corpus?.length && (
              <details>
                <summary>创作样例（{seed.corpus.length} 组）</summary>
                {seed.corpus.slice(0, 3).map((item, index) => (
                  <div key={index} className="my-3 text-sm">
                    <p>{item.user}</p>
                    <p>{item.assistant}</p>
                  </div>
                ))}
              </details>
            )}
            <p className="rounded-xl border p-4 text-sm">
              应用会新增一个人格版本，用上面的设定替换当前设定，保留历史。已积累的成长内容不会自动合并；需要保留时请先保存为个人包。
            </p>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={busy || blocked || reviewRequired}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>我已核对差异，确认替换当前人格设定</span>
            </label>
            <div className="flex flex-wrap gap-2">
              <Button
                disabled={busy || blocked || reviewRequired || !confirmed}
                onClick={onInstall}
              >
                应用此包
              </Button>
              <Button
                variant="outline"
                disabled={busy || blocked}
                onClick={onEdit}
              >
                {selected.reference.startsWith("mine/")
                  ? "编辑已保存包"
                  : "复制到我的包"}
              </Button>
              <Button variant="outline" disabled={busy} onClick={onExport}>
                导出完整包
              </Button>
              <Button
                variant="ghost"
                disabled={busy}
                onClick={() => downloadPack(seed, `${seed.id}.json`)}
              >
                导出设定 JSON
              </Button>
            </div>
            {selected.reference.startsWith("mine/") && (
              <div className="space-y-2 border-t pt-4">
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={removeConfirmed}
                    disabled={busy || blocked}
                    onChange={(e) => setRemoveConfirmed(e.target.checked)}
                  />
                  确认移除此包；当前人格内容保留，封面可能变为占位图
                </label>
                <Button
                  variant="ghost"
                  disabled={busy || blocked || !removeConfirmed}
                  onClick={onRemove}
                >
                  移入回收目录
                </Button>
              </div>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        {(error || reviewRequired) && (
          <Button variant="outline" disabled={busy} onClick={onReload}>
            重新加载并核对
          </Button>
        )}
        <Button variant="ghost" disabled={busy} onClick={onClose}>
          取消
        </Button>
      </div>
    </DetailDrawer>
  )
}
