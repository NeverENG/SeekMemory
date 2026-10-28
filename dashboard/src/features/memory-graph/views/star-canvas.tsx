import { useEffect, useRef, useState } from "react"
import { Button } from "@/ui"
import { Focus, Minus, Plus, RotateCcw, Pause, Play } from "lucide-react"
import type { GraphSnapshot } from "@/features/shell/model"
import { kindColors, kindLabels } from "../model"
import { hitStar } from "../draw-scene"
import type { ManagementClient } from "@/features/control/model"
import { MemoryCallout } from "./memory-callout"
import { useStarScene } from "./use-star-scene"
export function StarCanvas({
  graph,
  selected,
  foreground,
  onSelect,
  onReset,
  replay,
  readDetail,
  onInspect,
}: {
  graph: GraphSnapshot
  replay: GraphSnapshot
  readDetail: ManagementClient["detail"]
  onInspect: (id: string) => void
  selected: string
  foreground: string
  onSelect: (id: string) => void
  onReset: () => void
}) {
  const [hovered, setHovered] = useState("")
  const [paused, setPaused] = useState(false)
  const visibleHovered = graph.nodes.some((node) => node.id === hovered)
    ? hovered
    : ""
  const {
    canvas,
    screen,
    zoom,
    rotate,
    resetOrbit,
    focusNode,
    setDragging,
    tooltip,
    leader,
  } = useStarScene(graph, foreground, selected, visibleHovered, paused, replay)
  const pointers = useRef(new Map<number, { x: number; y: number }>())
  const drag = useRef({ id: "", distance: 0 })
  const hoveredId = useRef("")
  const hover = (id: string) => {
    hoveredId.current = id
    setHovered(id)
  }
  const reset = () => {
    resetOrbit()
    hover("")
    onReset()
  }
  const active = graph.nodes.find((n) => n.id === (selected || visibleHovered))
  useEffect(() => {
    const node = canvas.current
    if (!node) return
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      zoom(Math.exp(-event.deltaY * 0.001))
    }
    node.addEventListener("wheel", wheel, { passive: false })
    return () => node.removeEventListener("wheel", wheel)
  }, [canvas, zoom])
  const release = (id: number) => {
    pointers.current.delete(id)
    setDragging(pointers.current.size > 0)
  }
  return (
    <div className="star-canvas">
      <canvas
        ref={canvas}
        tabIndex={0}
        role="img"
        aria-label="立体记忆球。拖动旋转，滚轮或双指缩放；悬停查看摘要，点击展开详细信息。方向键旋转，加减键缩放，Escape 取消选择。"
        style={{
          width: "100%",
          height: "100%",
          touchAction: "none",
          cursor: hovered ? "pointer" : "grab",
        }}
        onKeyDown={(e) => {
          if (e.key === "+" || e.key === "=") zoom(1.15)
          else if (e.key === "-") zoom(1 / 1.15)
          else if (e.key === "Escape") {
            hover("")
            onSelect("")
          } else if (
            ["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(e.key)
          ) {
            e.preventDefault()
            rotate(
              (Number(e.key === "ArrowRight") - Number(e.key === "ArrowLeft")) *
                0.12,
              (Number(e.key === "ArrowDown") - Number(e.key === "ArrowUp")) *
                0.12
            )
          }
        }}
        onPointerDown={(e) => {
          const rect = e.currentTarget.getBoundingClientRect(),
            x = e.clientX - rect.left,
            y = e.clientY - rect.top
          pointers.current.set(e.pointerId, { x, y })
          setDragging(true)
          drag.current = {
            id: hitStar(screen.current, x, y, hoveredId.current),
            distance: pointers.current.size > 1 ? 100 : 0,
          }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect(),
            x = e.clientX - rect.left,
            y = e.clientY - rect.top
          const previous = pointers.current.get(e.pointerId)
          if (!previous) {
            if (!selected)
              hover(hitStar(screen.current, x, y, hoveredId.current))
            return
          }
          const other = [...pointers.current.entries()].find(
            ([id]) => id !== e.pointerId
          )?.[1]
          if (other) {
            drag.current.distance = 100
            const distance = Math.hypot(
              previous.x - other.x,
              previous.y - other.y
            )
            if (distance > 0)
              zoom(Math.hypot(x - other.x, y - other.y) / distance)
          } else {
            const dx = x - previous.x,
              dy = y - previous.y
            drag.current.distance += Math.hypot(dx, dy)
            if (drag.current.distance > 4) {
              hover("")
              rotate(dx * 0.006, dy * 0.006)
            }
          }
          pointers.current.set(e.pointerId, { x, y })
        }}
        onPointerUp={(e) => {
          if (drag.current.distance < 5 && pointers.current.size === 1) {
            const id = drag.current.id
            onSelect(id === selected ? "" : id)
            if (e.pointerType !== "mouse") hover("")
          }
          release(e.pointerId)
          if (e.currentTarget.hasPointerCapture(e.pointerId))
            e.currentTarget.releasePointerCapture(e.pointerId)
        }}
        onPointerCancel={(e) => {
          drag.current.distance = 100
          release(e.pointerId)
          hover("")
        }}
        onLostPointerCapture={(e) => release(e.pointerId)}
        onPointerLeave={() => hover("")}
      />
      {active && (
        <div
          key={active.id}
          className="sphere-annotation"
          style={{ color: kindColors[active.kind] }}
        >
          <svg className="sphere-leader" aria-hidden="true">
            <path ref={leader} />
          </svg>
          <div
            ref={tooltip}
            className={`sphere-callout ${selected ? "is-expanded" : ""}`}
            role={selected ? "region" : "status"}
            aria-label={selected ? "选中记忆详情" : undefined}
          >
            <div className="sphere-callout-kind">
              <i />
              {kindLabels[active.kind] ?? active.kind}
              {active.protected && <span>内容受保护</span>}
            </div>
            {selected ? (
              <MemoryCallout
                node={active}
                readDetail={readDetail}
                onInspect={onInspect}
                onClose={() => {
                  hover("")
                  onSelect("")
                }}
              />
            ) : (
              <p>{active.label}</p>
            )}
          </div>
        </div>
      )}
      <div className="star-controls">
        {selected && (
          <Button
            variant="outline"
            size="icon"
            aria-label="聚焦选中记忆"
            onClick={() => focusNode(selected)}
          >
            <Focus />
          </Button>
        )}
        <Button
          variant="outline"
          size="icon"
          aria-label="放大星图"
          onClick={() => zoom(1.15)}
        >
          <Plus />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="缩小星图"
          onClick={() => zoom(1 / 1.15)}
        >
          <Minus />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label="重置星图"
          onClick={reset}
        >
          <RotateCcw />
        </Button>
        <Button
          variant="outline"
          size="icon"
          aria-label={paused ? "播放星图动效" : "暂停星图动效"}
          aria-pressed={paused}
          onClick={() => setPaused(!paused)}
        >
          {paused ? <Play /> : <Pause />}
        </Button>
      </div>
    </div>
  )
}
