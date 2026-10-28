import { useCallback, useEffect, useMemo, useRef } from "react"
import type { GraphSnapshot } from "../../shell/model.ts"
import { assemblyDuration, entranceCamera } from "../choreography.ts"
import { focusOrbit, layoutSphere, type Orbit } from "../scene.ts"
import { drawScene, scenePalette, type ScreenStar } from "../draw-scene.ts"
export function useStarScene(
  graph: GraphSnapshot,
  kind: string,
  selected: string,
  hovered: string,
  paused: boolean,
  replay: GraphSnapshot
) {
  const canvas = useRef<HTMLCanvasElement>(null),
    tooltip = useRef<HTMLDivElement>(null),
    leader = useRef<SVGPathElement>(null)
  const screen = useRef<ScreenStar[]>([])
  const orbit = useRef<Orbit>({ yaw: 0.35, pitch: -0.18, zoom: 1 })
  const entrance = useRef(0)
  const dragging = useRef(false),
    invalidate = useRef(() => {})
  const sphere = useMemo(() => layoutSphere(graph), [graph])
  const relations = useMemo(
    (): [string, string][] =>
      graph.edges
        .filter((e) => e.source === selected || e.target === selected)
        .map((e) => [e.source, e.target]),
    [graph, selected]
  )
  const latest = useRef({
    sphere,
    kind,
    selected,
    hovered,
    paused,
    relations,
    replay,
  })
  useEffect(() => {
    latest.current = {
      sphere,
      kind,
      selected,
      hovered,
      paused,
      relations,
      replay,
    }
    invalidate.current()
  }, [sphere, kind, selected, hovered, paused, relations, replay])
  // The canvas, observers and clock have one lifetime; pointer updates never resize/restart them.
  useEffect(() => {
    const element = canvas.current,
      ctx = element?.getContext("2d")
    if (!element || !ctx) return
    const media = window.matchMedia("(prefers-reduced-motion: reduce)")
    let palette = scenePalette(element),
      frame = 0,
      visible = true,
      last = 0,
      elapsed = 0,
      width = 0,
      height = 0,
      dirtyFrames = 0,
      intro = 0
    let lastReplay = latest.current.replay
    const lifts = new Map<string, number>()
    const drawSamples: number[] = [],
      frameSamples: number[] = []
    const schedule = () => {
      if (!frame && visible && !document.hidden)
        frame = requestAnimationFrame(render)
    }
    // Keep one follow-up paint after layout/theme invalidation, including paused canvases.
    const repaint = () => {
      dirtyFrames = 2
      schedule()
    }
    const render = (now: number) => {
      frame = 0
      if (document.hidden || !visible || width <= 0 || height <= 0) {
        last = 0
        return
      }
      const frameMs = last ? now - last : 0
      const dt = last ? Math.min(40, frameMs) : 16.7
      last = now
      const state = latest.current
      if (state.replay !== lastReplay) {
        intro = 0
        entrance.current = 0
        orbit.current = { yaw: 0.35, pitch: -0.18, zoom: 1 }
        lastReplay = state.replay
      }
      intro = Math.max(intro, entrance.current)
      if (media.matches || state.paused) intro = assemblyDuration
      else intro = Math.min(assemblyDuration, intro + dt)
      entrance.current = intro
      const assembling =
        intro < assemblyDuration && state.sphere.stars.length > 0
      const active = state.selected || state.hovered
      const animate =
        state.sphere.stars.length > 0 &&
        !media.matches &&
        !state.paused &&
        !state.hovered &&
        !dragging.current
      if (animate && !assembling) {
        elapsed += dt
        if (!state.selected && !assembling) orbit.current.yaw -= dt * 0.000085
      }
      let settling = false
      const ids = new Set([...lifts.keys(), active].filter(Boolean))
      for (const id of ids) {
        const target = id === active ? 1 : 0,
          previous = lifts.get(id) ?? 0
        const next = media.matches
          ? target
          : previous + (target - previous) * (1 - Math.exp(-dt / 75))
        if (Math.abs(target - next) > 0.005) settling = true
        if (next < 0.005 && !target) lifts.delete(id)
        else lifts.set(id, Math.abs(target - next) < 0.005 ? target : next)
      }
      const before = performance.now()
      screen.current = drawScene(
        ctx,
        width,
        height,
        state.sphere,
        { ...state, orbit: orbit.current, time: elapsed, intro, lifts },
        palette
      )
      const point = screen.current.find((p) => p.id === active)
      if (tooltip.current && point) {
        const card = tooltip.current,
          w = card.offsetWidth,
          h = card.offsetHeight
        const right = point.sx + w + 42 < width
        const x = Math.max(
          12,
          Math.min(width - w - 12, right ? point.sx + 32 : point.sx - w - 32)
        )
        const y = Math.max(12, Math.min(height - h - 58, point.sy - h / 2))
        card.style.transform = `translate3d(${x}px, ${y}px, 0)`
        const endX = right ? x : x + w,
          endY = y + 22
        leader.current?.setAttribute(
          "d",
          `M${point.sx},${point.sy} L${endX + (right ? -12 : 12)},${endY} L${endX},${endY}`
        )
      }
      if (import.meta.env.DEV) {
        const drawMs = performance.now() - before
        drawSamples.push(drawMs)
        if (frameMs > 0 && frameMs < 1000) frameSamples.push(frameMs)
        if (drawSamples.length > 120) drawSamples.shift()
        if (frameSamples.length > 120) frameSamples.shift()
        const p95 = (samples: number[]) =>
          [...samples].sort((a, b) => a - b)[
            Math.floor((samples.length - 1) * 0.95)
          ] ?? 0
        element.dataset["drawP95"] = p95(drawSamples).toFixed(2)
        element.dataset["frameP95"] = p95(frameSamples).toFixed(2)
        element.dataset["samples"] = String(drawSamples.length)
        element.dataset["intro"] = intro.toFixed(0)
        element.dataset["stage"] =
          ["seed", "trunk", "branches", "pullback", "ready"][
            [700, 1600, 4300, assemblyDuration].filter((end) => intro >= end)
              .length
          ] ?? "ready"
        element.dataset["nodes"] = String(state.sphere.stars.length)
        element.dataset["renderedAt"] = now.toFixed(1)
        element.dataset["drawMs"] = (performance.now() - before).toFixed(3)
        element.dataset["frameMs"] = frameMs.toFixed(2)
        element.dataset["bitmapBytes"] = String(
          element.width * element.height * 4
        )
      }
      dirtyFrames = Math.max(0, dirtyFrames - 1)
      if (animate || assembling || settling || dirtyFrames > 0) schedule()
    }
    invalidate.current = repaint
    const resize = () => {
      const rect = element.getBoundingClientRect(),
        dpr = Math.min(window.devicePixelRatio || 1, 1.5)
      width = rect.width
      height = rect.height
      const w = Math.round(width * dpr),
        h = Math.round(height * dpr)
      if (element.width !== w || element.height !== h) {
        element.width = w
        element.height = h
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      repaint()
    }
    const observer = new ResizeObserver(resize)
    observer.observe(element)
    resize()
    const intersection = new IntersectionObserver((entries) => {
      visible = entries[0]?.isIntersecting ?? true
      if (import.meta.env.DEV) element.dataset["intersecting"] = String(visible)
      last = 0
      repaint()
    })
    intersection.observe(element)
    const theme = new MutationObserver(() => {
      palette = scenePalette(element)
      repaint()
    })
    theme.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    })
    const wake = () => {
      last = 0
      repaint()
    }
    document.addEventListener("visibilitychange", wake)
    media.addEventListener("change", wake)
    element.addEventListener("contextrestored", resize)
    return () => {
      cancelAnimationFrame(frame)
      invalidate.current = () => {}
      observer.disconnect()
      intersection.disconnect()
      theme.disconnect()
      document.removeEventListener("visibilitychange", wake)
      media.removeEventListener("change", wake)
      element.removeEventListener("contextrestored", resize)
    }
  }, [])
  useEffect(() => {
    const card = tooltip.current
    if (!card) return
    const observer = new ResizeObserver(() => invalidate.current())
    observer.observe(card)
    return () => observer.disconnect()
  }, [selected, hovered])
  const takeControl = useCallback(() => {
    if (entrance.current >= assemblyDuration) return
    const state = latest.current
    const camera = entranceCamera(
      state.sphere.propagation,
      state.sphere.stars,
      entrance.current
    )
    const settled = entranceCamera(
      state.sphere.propagation,
      state.sphere.stars,
      assemblyDuration
    )
    orbit.current = {
      yaw: orbit.current.yaw + camera.yaw - settled.yaw,
      pitch: orbit.current.pitch + camera.pitch,
      zoom: orbit.current.zoom * camera.zoom,
      focus: camera.focus,
      offsetX: camera.offsetX,
      roll: camera.roll,
    }
    entrance.current = assemblyDuration
  }, [])
  const zoom = useCallback(
    (factor: number) => {
      takeControl()
      orbit.current.zoom = Math.min(
        2.5,
        Math.max(0.55, orbit.current.zoom * factor)
      )
      invalidate.current()
    },
    [takeControl]
  )
  const rotate = useCallback(
    (yaw: number, pitch: number) => {
      takeControl()
      orbit.current.yaw += yaw
      orbit.current.pitch += pitch
      invalidate.current()
    },
    [takeControl]
  )
  const resetOrbit = useCallback(() => {
    entrance.current = assemblyDuration
    orbit.current = { yaw: 0.35, pitch: -0.18, zoom: 1 }
    invalidate.current()
  }, [])
  const focusNode = useCallback((id: string) => {
    const point = latest.current.sphere.stars.find((star) => star.id === id)
    if (!point) return
    entrance.current = assemblyDuration
    const state = latest.current
    const settled = entranceCamera(
      state.sphere.propagation,
      state.sphere.stars,
      assemblyDuration
    )
    const focused = focusOrbit(point)
    orbit.current = { ...focused, yaw: focused.yaw - settled.yaw }
    invalidate.current()
  }, [])
  const setDragging = useCallback(
    (value: boolean) => {
      if (value) takeControl()
      dragging.current = value
      invalidate.current()
    },
    [takeControl]
  )
  return {
    canvas,
    screen,
    zoom,
    rotate,
    resetOrbit,
    focusNode,
    setDragging,
    tooltip,
    leader,
  }
}
