import { useCallback, useMemo, useState } from "react"
import { Button } from "@/ui"
import { PageIntro, ResourceState } from "@/features/shell/page-parts"
import { useResource } from "@/features/shell/use-resource"
import type { ConsoleClient, GraphSort } from "@/features/shell/model"
import {
  focusGraph,
  displayGraph,
  memoryLimits,
  kindLabels,
  kindColors,
} from "../model"
import { graphLayers, edgeLabels } from "../scene"
import "./memory-map.css"
import type { ManagementClient } from "@/features/control/model"
import { StarCanvas } from "./star-canvas"
export function MemoryMap({
  client,
  initialNode,
  onInspect,
  readDetail,
}: {
  client: ConsoleClient
  readDetail: ManagementClient["detail"]
  initialNode: string
  onInspect: (id: string) => void
}) {
  const [limit, setLimit] = useState(80)
  const [sort, setSort] = useState<GraphSort>("weight")
  const read = useCallback(() => client.graph(sort), [client, sort])
  const vm = useResource(read)
  const [layer, setLayer] = useState("")
  const [selected, setSelected] = useState(initialNode)
  const [focus, setFocus] = useState("")
  const matching = useMemo(
    () => (vm.data ? focusGraph(vm.data, focus) : null),
    [vm.data, focus]
  )
  const filtered = useMemo(
    () => (matching ? displayGraph(matching, limit) : null),
    [matching, limit]
  )
  const nodes = filtered?.nodes ?? []
  const current = nodes.find((n) => n.id === selected)
  const layers = filtered ? graphLayers(filtered) : []
  const foreground = layers.includes(layer) ? layer : ""
  const selectNode = (id: string) => {
    setSelected(id)
  }
  const resetView = () => {
    setSelected("")
    setLayer("")
    setFocus("")
  }
  const relationKinds = [
    ...new Set(
      filtered?.edges
        .filter((edge) => edge.source === selected || edge.target === selected)
        .map((edge) => edgeLabels[edge.kind] ?? edge.kind) ?? []
    ),
  ]
  return (
    <div className="console-page console-map-page">
      <PageIntro title="记忆星图" />
      <ResourceState
        loading={vm.loading}
        error={vm.error}
        onRetry={vm.reload}
      />
      {vm.data && filtered && (
        <>
          <div
            className="constellation-layers"
            role="group"
            aria-label="高亮记忆类型"
          >
            {layers.map((value) => (
              <button
                key={value}
                aria-pressed={foreground === value}
                onClick={() => {
                  setLayer(layer === value ? "" : value)
                  setSelected("")
                }}
              >
                <i style={{ background: kindColors[value] }} />
                {kindLabels[value] ?? value}
              </button>
            ))}
          </div>
          <div className="console-panel constellation-surface">
            <div className="map-status">
              <label className="sphere-limit">
                排序
                <select
                  aria-label="星图排序"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value === "recent" ? "recent" : "weight")
                    resetView()
                  }}
                >
                  <option value="weight">高权重优先</option>
                  <option value="recent">最近更新</option>
                </select>
              </label>
              <label className="sphere-limit">
                显示
                <select
                  aria-label="星图记忆数量上限"
                  value={limit}
                  onChange={(e) => {
                    setLimit(Number(e.target.value))
                    setSelected("")
                  }}
                >
                  {memoryLimits.map((n) => (
                    <option key={n} value={n}>
                      {n} 条
                    </option>
                  ))}
                </select>
              </label>
              {focus ? (
                <Button variant="ghost" onClick={() => setFocus("")}>
                  退出关联视图
                </Button>
              ) : (
                current && (
                  <Button variant="ghost" onClick={() => setFocus(current.id)}>
                    只看关联记忆
                  </Button>
                )
              )}
            </div>
            <StarCanvas
              graph={filtered}
              replay={vm.data}
              readDetail={readDetail}
              onInspect={onInspect}
              selected={current?.id ?? ""}
              onSelect={selectNode}
              foreground={foreground}
              onReset={resetView}
            />
            <div className="map-selection">
              {current ? (
                <>
                  <div className="min-w-0">
                    <p className="line-clamp-2 text-sm">{current.label}</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {kindLabels[current.kind] ?? current.kind}
                      {current.protected ? " · 内容受保护" : ""}
                      {relationKinds.length
                        ? ` · ${relationKinds.join(" / ")}`
                        : " · 暂无关联"}
                    </p>
                  </div>
                </>
              ) : (
                <span>
                  {nodes.length
                    ? "拖动旋转 · 悬停预览 · 点击展开"
                    : "暂无可展示的记忆"}
                </span>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
