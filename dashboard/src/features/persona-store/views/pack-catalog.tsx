import { useState } from "react"
import { Search } from "lucide-react"
import { Button, Input } from "@/ui"
import { ResourceState } from "@/features/shell/page-parts"
import type { ConsoleClient, PersonaPack } from "@/features/shell/model"
import type { RuntimeStatus } from "@/features/control/model"
import { packInstallLabel } from "../model"
import { PackArtwork } from "./pack-artwork"

export function PackCatalog({
  client,
  data,
  loading,
  error,
  onRetry,
  status,
  busy,
  offset,
  onOffset,
  onPreview,
}: {
  client: ConsoleClient
  data: Awaited<ReturnType<ConsoleClient["packs"]>> | null
  loading: boolean
  error: string
  onRetry: () => Promise<void>
  status: RuntimeStatus | null
  busy: boolean
  offset: number
  onOffset: (offset: number) => void
  onPreview: (pack: PersonaPack) => void
}) {
  const [query, setQuery] = useState("")
  const items =
    data?.items.filter((pack) =>
      `${pack.name} ${pack.description}`
        .toLowerCase()
        .includes(query.toLowerCase())
    ) ?? []
  return (
    <>
      <div className="console-toolbar">
        <Search size={16} />
        <Input
          aria-label="搜索当前页人格包"
          placeholder="搜索当前页的人格包…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="max-w-sm"
        />
        <span className="ml-auto text-xs text-muted-foreground">
          {data?.total ?? 0} 个人格包
        </span>
      </div>
      <ResourceState
        loading={loading}
        error={error}
        empty={!!data && !items.length}
        onRetry={onRetry}
      />
      <div className="store-grid">
        {items.map((pack) => (
          <button
            type="button"
            className="console-panel seed-card"
            key={pack.reference}
            disabled={busy}
            onClick={() => onPreview(pack)}
          >
            <div className="seed-art seed-art-neutral">
              <PackArtwork pack={pack} client={client} />
            </div>
            <div className="space-y-3 p-5 text-left">
              <h2 className="text-lg font-semibold">{pack.name}</h2>
              <p className="line-clamp-2 text-sm text-muted-foreground">
                {pack.description}
              </p>
              <p className="text-xs text-muted-foreground">
                v{pack.version}
                {packInstallLabel(pack, status?.persona)}
              </p>
            </div>
          </button>
        ))}
      </div>
      {data && data.total > 24 && (
        <div className="console-toolbar mt-5">
          <Button
            disabled={!offset || busy}
            onClick={() => onOffset(Math.max(0, offset - 24))}
          >
            上一页
          </Button>
          <Button
            disabled={offset + 24 >= data.total || busy}
            onClick={() => onOffset(offset + 24)}
          >
            下一页
          </Button>
        </div>
      )}
    </>
  )
}
