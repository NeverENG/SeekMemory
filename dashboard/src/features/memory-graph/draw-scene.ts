import {
  assemblyDuration,
  smooth,
  entranceCamera,
  nodeReveal,
  edgeReveal,
  pulseAt,
} from "./choreography.ts"
import { sphereRadius, surfaceWave } from "./motion.ts"
import { kindColors } from "./model.ts"
import { rotatePoint, type Orbit, type Sphere, type Star } from "./scene.ts"
export type ScreenStar = Star & {
  sx: number
  sy: number
  bx: number
  by: number
  depth: number
  r: number
  light?: number
  reveal?: number
}
export type ScenePalette = {
  colors: Record<string, string>
  muted: string
  pulse: string
  core: string
  line: string
  dark: boolean
}
export function scenePalette(element: HTMLElement): ScenePalette {
  const style = getComputedStyle(element)
  const token = (key: string) => style.getPropertyValue(key).trim()
  return {
    colors: Object.fromEntries(
      Object.entries(kindColors).map(([kind, value]) => [
        kind,
        token(value.slice(4, -1)),
      ])
    ),
    muted: token("--muted-foreground"),
    pulse: token("--graph-pulse"),
    core: token("--graph-core"),
    line: token("--graph-wire"),
    dark: document.documentElement.dataset["theme"] === "dark",
  }
}
export type SceneInput = {
  orbit: Orbit
  selected: string
  hovered: string
  kind: string
  time: number
  intro: number
  lifts: Map<string, number>
  relations: [string, string][]
}
export function drawScene(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  sphere: Sphere,
  input: SceneInput,
  palette: ScenePalette
): ScreenStar[] {
  ctx.clearRect(0, 0, width, height)
  const { orbit, time, lifts } = input
  const plan = sphere.propagation
  const camera = entranceCamera(plan, sphere.stars, input.intro)
  const cameraOrbit = {
    ...orbit,
    yaw: orbit.yaw + camera.yaw,
    pitch: orbit.pitch + camera.pitch,
    roll: (orbit.roll ?? 0) + camera.roll,
  }
  const focus = rotatePoint(orbit.focus ?? camera.focus, cameraOrbit)
  const lens = 3.7 / (3.7 - focus.z)
  const assembled = input.intro >= assemblyDuration
  const radius =
    sphereRadius(width, height, sphere.stars.length) * orbit.zoom * camera.zoom
  const breathe = assembled ? 1 + Math.sin(time * 0.00065) * 0.012 : 1
  const size = Math.max(2.8, 4.4 - Math.sqrt(sphere.stars.length) * 0.08)
  const projected = sphere.stars.map((star, i): ScreenStar => {
    const p = rotatePoint(star, cameraOrbit),
      perspective = 3.7 / (3.7 - p.z)
    const light = surfaceWave(star.y, star.z, time)
    const ripple = assembled ? light * 0.028 : 0
    const scale = radius * perspective * (breathe + ripple)
    const lift = lifts.get(star.id) ?? 0
    return {
      ...star,
      light,
      reveal: nodeReveal(plan, i, input.intro),
      bx:
        width / 2 +
        width * (orbit.offsetX ?? camera.offsetX) +
        p.x * scale -
        focus.x * radius * lens,
      by: height / 2 - p.y * scale + focus.y * radius * lens,
      sx:
        width / 2 +
        width * (orbit.offsetX ?? camera.offsetX) +
        p.x * scale * (1 + lift * 0.07) -
        focus.x * radius * lens,
      sy:
        height / 2 - p.y * scale * (1 + lift * 0.07) + focus.y * radius * lens,
      depth: p.z,
      r: size * perspective * (1 + lift * 0.8),
    }
  })
  // Faces exist only in the assembly flash or beneath a moving surface ripple.
  for (const [a, b, c] of sphere.faces) {
    const p = projected[a],
      q = projected[b],
      r = projected[c]
    if (!p || !q || !r) continue
    const facing = (q.sx - p.sx) * (r.sy - p.sy) - (q.sy - p.sy) * (r.sx - p.sx)
    if (facing >= 0) continue
    ctx.fillStyle = palette.colors[p.kind] ?? palette.muted
    const emphasis = !input.kind || p.kind === input.kind ? 1 : 0.3
    const waveLight = ((p.light ?? 0) + (q.light ?? 0) + (r.light ?? 0)) / 3
    const arrived = Math.min(p.reveal ?? 0, q.reveal ?? 0, r.reveal ?? 0)
    const birth = Math.max(
      plan.births[a] ?? 0,
      plan.births[b] ?? 0,
      plan.births[c] ?? 0
    )
    // The intro clock stops at assemblyDuration. Fade all remaining entry
    // highlights before that boundary, or late facets remain lit forever.
    const flash = assembled
      ? 0
      : Math.sin(
          Math.PI * Math.max(0, Math.min(1, (input.intro - birth - 300) / 800))
        ) * smooth((assemblyDuration - input.intro) / 350)
    ctx.globalAlpha =
      Math.max(flash * 0.12, waveLight * 0.18 * Number(assembled)) *
      emphasis *
      arrived
    if (ctx.globalAlpha < 0.004) continue
    ctx.beginPath()
    ctx.moveTo(p.sx, p.sy)
    ctx.lineTo(q.sx, q.sy)
    ctx.lineTo(r.sx, r.sy)
    ctx.closePath()
    ctx.fill()
  }
  ctx.lineWidth = 0.9
  ctx.strokeStyle = palette.line
  for (const [a, b] of sphere.edges) {
    const edge = edgeReveal(plan, a, b, input.intro)
    const p = projected[edge.from],
      q = projected[edge.to]
    if (!p || !q) continue
    const depth = (p.depth + q.depth) / 2
    // Back-facing/polar closure edges fade into the completed surface; only
    // rightward foreground edges trace out the advancing front.
    const extending = q.sx > p.sx && depth > -0.15
    const length = extending ? edge.progress : 1
    ctx.globalAlpha =
      (depth < -0.1 ? 0.08 : 0.25 + Math.max(0, depth) * 0.3) *
      edge.opacity *
      (extending ? Math.min(1, edge.progress * 4) : edge.progress)
    ctx.beginPath()
    ctx.moveTo(p.sx, p.sy)
    ctx.lineTo(p.sx + (q.sx - p.sx) * length, p.sy + (q.sy - p.sy) * length)
    ctx.stroke()
  }
  const byId = new Map(projected.map((p) => [p.id, p]))
  // Actual relationships are shown separately from the geometric surface mesh.
  ctx.setLineDash([3, 5])
  ctx.lineWidth = 1.2
  for (const [a, b] of input.relations) {
    const p = byId.get(a),
      q = byId.get(b)
    if (!p || !q) continue
    ctx.globalAlpha = 0.35
    ctx.strokeStyle = palette.colors[p.kind] ?? palette.line
    ctx.beginPath()
    ctx.moveTo(p.sx, p.sy)
    ctx.lineTo(q.sx, q.sy)
    ctx.stroke()
  }
  ctx.setLineDash([])
  // A single full-edge color pulse. No moving head or detached tail; its endpoint
  // is the next pulse's source. The broad envelope travels within the existing line.
  const pulse = assembled ? pulseAt(plan, time) : null
  if (pulse) {
    const p = projected[pulse.from],
      q = projected[pulse.to]
    if (p && q) {
      const tint = palette.pulse
      const envelope = Math.sin(pulse.phase * Math.PI)
      const gradient = ctx.createLinearGradient(p.sx, p.sy, q.sx, q.sy)
      for (let stop = 0; stop <= 12; stop++) {
        const position = stop / 12
        const strength =
          Math.exp(-((position - pulse.phase) ** 2) / 0.16) * envelope
        gradient.addColorStop(
          position,
          `${tint}${Math.round(strength * 150)
            .toString(16)
            .padStart(2, "0")}`
        )
      }
      ctx.globalAlpha = 0.45 + Math.max(0, (p.depth + q.depth) / 2) * 0.55
      ctx.strokeStyle = gradient
      ctx.lineWidth = 1.65
      ctx.shadowColor = tint
      ctx.shadowBlur = palette.dark ? 3 : 1
      ctx.beginPath()
      ctx.moveTo(p.sx, p.sy)
      ctx.lineTo(q.sx, q.sy)
      ctx.stroke()
      ctx.shadowBlur = 0
    }
  }
  const ordered = [...projected].sort((a, b) => a.depth - b.depth)
  for (const p of ordered) {
    const active = p.id === input.hovered || p.id === input.selected,
      color = palette.colors[p.kind] ?? palette.muted
    const emphasis = !input.kind || p.kind === input.kind || active ? 1 : 0.24
    const alpha = (0.32 + (p.depth + 1) * 0.34) * emphasis * (p.reveal ?? 1)
    ctx.fillStyle = color
    // Compact, crisp points with only a close light rim, no diffuse color clouds.
    ctx.fillStyle = color
    ctx.globalAlpha = alpha
    ctx.shadowColor = color
    // Dense snapshots keep crisp colored points; reserve costly blur for selection.
    ctx.shadowBlur = sphere.stars.length > 120 ? 0 : 1.5
    if (active) ctx.shadowBlur = 5
    ctx.beginPath()
    ctx.arc(p.sx, p.sy, p.r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
    ctx.fillStyle = palette.dark ? palette.core : color
    ctx.globalAlpha = alpha * 0.9
    ctx.beginPath()
    ctx.arc(p.sx, p.sy, p.r * 0.28, 0, Math.PI * 2)
    ctx.fill()
    if (active) {
      ctx.strokeStyle = color
      ctx.lineWidth = 0.8
      ctx.globalAlpha = 0.4
      ctx.beginPath()
      ctx.arc(p.sx, p.sy, p.r + 5, 0, Math.PI * 2)
      ctx.stroke()
    }
  }
  ctx.globalAlpha = 1
  return projected
}
/** Hit-test the unlifted position as well, preventing hover oscillation while a point rises. */
export function hitStar(
  stars: ScreenStar[],
  x: number,
  y: number,
  retained = ""
): string {
  const held = stars.find((p) => p.id === retained)
  const distance = (p: ScreenStar) =>
    Math.min(Math.hypot(p.sx - x, p.sy - y), Math.hypot(p.bx - x, p.by - y))
  if (held && distance(held) < Math.max(20, held.r + 10)) return held.id
  let best: ScreenStar | undefined,
    nearest = Infinity
  for (const p of stars) {
    if (p.depth < -0.15 || (p.reveal ?? 1) < 0.8) continue
    const d = distance(p)
    if (
      d < Math.max(10, p.r + 5) &&
      (d < nearest - 2 ||
        (Math.abs(d - nearest) < 2 && p.depth > (best?.depth ?? -1)))
    ) {
      best = p
      nearest = d
    }
  }
  return best?.id ?? ""
}
