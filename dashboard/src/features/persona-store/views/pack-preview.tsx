import { PackArtwork } from "./pack-artwork"
import type { ConsoleClient } from "@/features/shell/model"
import { Download } from "lucide-react"
import { Badge, Button, DetailDrawer } from "@/ui"
import type { PersonaPack, PersonaSeed } from "@/features/shell/model"
import type { RuntimeStatus } from "@/features/control/model"
export function PackPreview({
  client,
  licenseText,
  onExport,
  selected,
  seed,
  error,
  busy,
  status,
  confirmed,
  setConfirmed,
  removeConfirmed,
  setRemoveConfirmed,
  onClose,
  onInstall,
  onRemove,
}: {
  client: ConsoleClient
  licenseText: string
  onExport: () => void
  selected: PersonaPack | null
  seed: PersonaSeed | null
  error: string
  busy: boolean
  status: RuntimeStatus | null
  confirmed: boolean
  setConfirmed: (value: boolean) => void
  removeConfirmed: boolean
  setRemoveConfirmed: (value: boolean) => void
  onClose: () => void
  onInstall: () => void
  onRemove: () => void
}) {
  return (
    <DetailDrawer
      open={!!selected}
      onOpenChange={(open) => {
        if (!open && !busy) onClose()
      }}
      title={selected?.name ?? "人格预览"}
      description="查看设定、示例和来源后再安装"
    >
      <div className="space-y-5 p-6">
        {!seed && !error && <p role="status">正在读取人格…</p>}
        {seed && (
          <>
            {selected && (
              <div className="seed-art seed-art-neutral">
                <PackArtwork pack={selected} client={client} />
              </div>
            )}
            <div className="flex gap-2">
              <Badge>{seed.license || "许可未声明"}</Badge>
              <Badge variant="outline">
                {seed.content_rating === "general"
                  ? "全年龄"
                  : seed.content_rating || "未分级"}
              </Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              来源：{seed.source || "未声明"} · 版本 {seed.version}
            </p>
            {!!licenseText && (
              <details className="rounded-xl border p-4 text-sm">
                <summary>许可证正文</summary>
                <pre className="mt-3 font-sans whitespace-pre-wrap">
                  {licenseText}
                </pre>
              </details>
            )}
            <p className="leading-8 whitespace-pre-wrap">{seed.persona}</p>
            {!!seed.boundaries?.length && (
              <section>
                <h3 className="mb-2 font-semibold">相处的边界</h3>
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {seed.boundaries.map((line, index) => (
                    <li key={index}>· {line}</li>
                  ))}
                </ul>
              </section>
            )}
            {!!seed.corpus?.length && (
              <details className="rounded-xl border p-4">
                <summary>听听它会怎么说（创作示例）</summary>
                {seed.corpus.slice(0, 3).map((pair, index) => (
                  <div key={index} className="mt-4 text-sm leading-7">
                    <p className="text-muted-foreground">{pair.user}</p>
                    <p>{pair.assistant}</p>
                  </div>
                ))}
              </details>
            )}
            <label className="flex gap-2 text-sm">
              <input
                type="checkbox"
                checked={confirmed}
                disabled={busy}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              我确认用这个设定创建当前人格的新版本，旧版本仍保留。
            </label>
            <Button
              disabled={
                !confirmed ||
                busy ||
                !status?.ready ||
                !!status.activeTask ||
                !selected
              }
              onClick={onInstall}
            >
              安装 / 重新安装
            </Button>
            <Button
              variant="outline"
              className="ml-2"
              disabled={busy}
              onClick={() => {
                const blob = new Blob([JSON.stringify(seed, null, 2)], {
                  type: "application/json",
                })
                const url = URL.createObjectURL(blob)
                const link = document.createElement("a")
                link.href = url
                link.download = `${seed.id}.json`
                link.click()
                setTimeout(() => URL.revokeObjectURL(url), 1000)
              }}
            >
              <Download size={14} />
              导出设定
            </Button>
            <Button
              variant="outline"
              className="ml-2"
              disabled={busy}
              onClick={onExport}
            >
              导出完整包
            </Button>
            {selected?.reference.startsWith("mine/") && (
              <div className="space-y-3">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={removeConfirmed}
                    onChange={(e) => setRemoveConfirmed(e.target.checked)}
                  />
                  确认移除此本地包，当前人格不受影响
                </label>
                <Button
                  variant="ghost"
                  disabled={busy || !removeConfirmed}
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
      </div>
    </DetailDrawer>
  )
}
