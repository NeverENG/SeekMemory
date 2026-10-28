import { useState } from "react"
import { Button } from "@/ui"
import type { GraphNode } from "@/features/shell/model"
import { kindLabels } from "../model"

/** A bounded keyboard alternative to canvas hit-testing, using masked graph labels. */
export function MemoryList({
  nodes,
  selected,
  onSelect,
}: {
  nodes: GraphNode[]
  selected: string
  onSelect: (id: string) => void
}) {
  const [page, setPage] = useState(0)
  const lastPage = Math.max(0, Math.ceil(nodes.length / 30) - 1)
  const current = Math.min(page, lastPage)
  return (
    <section aria-label="记忆列表" className="space-y-3">
      <h3 className="text-sm font-medium">匹配的记忆 · {nodes.length} 条</h3>
      {!nodes.length && <p role="status">没有匹配的记忆</p>}
      <ul className="space-y-2">
        {nodes.slice(current * 30, (current + 1) * 30).map((node) => (
          <li key={node.id}>
            <button
              type="button"
              className="map-list-item"
              aria-pressed={node.id === selected}
              onClick={() => onSelect(node.id)}
            >
              <span className="text-xs text-muted-foreground">
                {kindLabels[node.kind] ?? node.kind}
                {node.protected ? " · 内容受保护" : ""}
              </span>
              <span className="line-clamp-2">{node.label}</span>
            </button>
          </li>
        ))}
      </ul>
      {lastPage > 0 && (
        <nav aria-label="记忆列表分页" className="flex items-center gap-3">
          <Button
            variant="outline"
            disabled={!current}
            onClick={() => setPage(current - 1)}
          >
            上一页
          </Button>
          <span aria-live="polite">
            {current + 1} / {lastPage + 1}
          </span>
          <Button
            variant="outline"
            disabled={current === lastPage}
            onClick={() => setPage(current + 1)}
          >
            下一页
          </Button>
        </nav>
      )}
    </section>
  )
}
