import { useCallback, useMemo, useState } from "react"
import { Button, Input, Select, DetailDrawer } from "@/ui"
import { PageIntro, ResourceState } from "@/features/shell/page-parts"
import { useResource } from "@/features/shell/use-resource"
import type { ConsoleClient, GraphSort } from "@/features/shell/model"
import {
  filterGraph,
  displayGraph,
  memoryLimits,
  kindLabels,
  kindColors,
} from "../model"
import { graphLayers, edgeLabels } from "../scene"
import "./memory-map.css"
import type { ManagementClient } from "@/features/control/model"
import { StarCanvas } from "./star-canvas"
import { MemoryList } from "./memory-list"
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
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [layer, setLayer] = useState("")
  const [query, setQuery] = useState(initialNode),
    [kind, setKind] = useState("all"),
    [scope, setScope] = useState("all"),
    [subject, setSubject] = useState("all"),
    [since, setSince] = useState("")
  const [selected, setSelected] = useState(initialNode)
  const [focus, setFocus] = useState("")
  const matching = useMemo(
    () =>
      vm.data
        ? filterGraph(vm.data, {
            query,
            kind,
            scope,
            subject,
            since,
            focus,
          })
        : null,
    [vm.data, query, kind, scope, subject, since, focus]
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
  const activeFilters = !!(
    query ||
    kind !== "all" ||
    scope !== "all" ||
    subject !== "all" ||
    since ||
    focus
  )
  return (
    <div className="console-page console-map-page">
      <PageIntro title="记忆星图">
        <Button variant="outline" onClick={() => setFiltersOpen(true)}>
          寻找记忆{activeFilters ? " · 已筛选" : ""}
        </Button>
      </PageIntro>
      <p className="mb-4 text-sm text-muted-foreground">
        高权重优先按系统记忆强度排序，不代表事实正确率。
        搜索和筛选仅覆盖当前加载的最多 120 条有效记忆。
        <a href="#/library" className="ml-2 underline">
          打开完整记忆库
        </a>
      </p>
      <ResourceState
        loading={vm.loading}
        error={vm.error}
        onRetry={vm.reload}
      />
      {vm.data && filtered && (
        <>
          <DetailDrawer
            open={filtersOpen}
            onOpenChange={setFiltersOpen}
            title="寻找记忆"
            description="仅筛选当前加载的最多 120 条有效记忆，不搜索全库"
          >
            <div className="map-filters">
              <Input
                aria-label="搜索记忆星图"
                placeholder="搜索当前星图快照…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <label htmlFor="graph-kind">
                记忆类型
                <Select
                  id="graph-kind"
                  label="星图记忆类型"
                  value={kind}
                  onValueChange={setKind}
                  options={[
                    { value: "all", label: "全部类型" },
                    ...Object.entries(kindLabels).map(([value, label]) => ({
                      value,
                      label,
                    })),
                  ]}
                />
              </label>
              <label htmlFor="graph-scope">
                可见范围
                <Select
                  id="graph-scope"
                  label="星图 scope"
                  value={scope}
                  onValueChange={setScope}
                  options={[
                    { value: "all", label: "全部范围" },
                    { value: "private", label: "私有" },
                    { value: "shared", label: "共享" },
                    { value: "shadow", label: "仅提供提示" },
                  ]}
                />
              </label>
              <label htmlFor="graph-subject">
                记忆对象
                <Select
                  id="graph-subject"
                  label="星图对象"
                  value={subject}
                  onValueChange={setSubject}
                  options={[
                    { value: "all", label: "全部对象" },
                    ...[
                      ...new Set(
                        vm.data.nodes.map((n) => n.subject).filter(Boolean)
                      ),
                    ].map((value) => ({ value, label: value })),
                  ]}
                />
              </label>
              <label htmlFor="graph-since">
                创建于此日期之后
                <Input
                  id="graph-since"
                  type="date"
                  aria-label="星图起始日期"
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                />
              </label>
              <Button
                variant="outline"
                onClick={() => {
                  setQuery("")
                  setKind("all")
                  setScope("all")
                  setSubject("all")
                  setSince("")
                  setFocus("")
                }}
              >
                清除筛选
              </Button>
              <Button onClick={() => setFiltersOpen(false)}>
                查看 {nodes.length} 条记忆
              </Button>
            </div>
            <MemoryList
              key={`${query}/${kind}/${scope}/${subject}/${since}/${focus}/${limit}`}
              nodes={nodes}
              selected={selected}
              onSelect={(id) => {
                selectNode(id)
                setFiltersOpen(false)
              }}
            />
          </DetailDrawer>
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
                    : "当前快照没有匹配的记忆，请调整筛选或打开完整记忆库"}
                </span>
              )}
            </div>
          </div>
          {vm.data.total > vm.data.nodes.length && (
            <p className="my-3 text-xs text-muted-foreground">
              当前加载 {vm.data.nodes.length} 条有效记忆，库内共 {vm.data.total}{" "}
              条（含非有效状态）。筛选仅作用于当前快照。
            </p>
          )}
        </>
      )}
    </div>
  )
}
