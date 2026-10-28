import { propagationPlan } from "./choreography.ts"
import type { GraphSnapshot } from "../shell/model.ts"
import { kindLabels } from "./model.ts"
import { sphereMesh, type Vec3 } from "./sphere-mesh.ts"
export type Star = Vec3 & { id: string; kind: string }
export type Sphere = ReturnType<typeof layoutSphere>
export function graphLayers(graph: GraphSnapshot): string[] {
  const present = new Set(graph.nodes.map((node) => node.kind))
  return [
    ...Object.keys(kindLabels).filter((kind) => present.has(kind)),
    ...[...present].filter((kind) => !(kind in kindLabels)).sort(),
  ]
}
/** Equal-area samples, partitioned spatially so each kind occupies one contiguous patch. */
export function layoutSphere(graph: GraphSnapshot) {
  const groups = graphLayers(graph).map((kind) =>
    graph.nodes
      .filter((n) => n.kind === kind)
      .sort((a, b) => a.id.localeCompare(b.id))
  )
  const count = graph.nodes.length
  const points = Array.from({ length: count }, (_, i): Vec3 => {
    const y = 1 - (2 * (i + 0.5)) / count,
      radius = Math.sqrt(1 - y * y),
      angle = i * 2.399963229728653
    return { x: Math.cos(angle) * radius, y, z: Math.sin(angle) * radius }
  })
  const stars: Star[] = []
  const assign = (pool: Vec3[], kinds: typeof groups) => {
    if (!kinds.length) return
    if (kinds.length === 1) {
      kinds[0]?.forEach((node, i) => {
        const p = pool[i]
        if (p) stars.push({ ...p, id: node.id, kind: node.kind })
      })
      return
    }
    const axes = ["x", "y", "z"] as const
    const span = (axis: (typeof axes)[number]) =>
      Math.max(...pool.map((p) => p[axis])) -
      Math.min(...pool.map((p) => p[axis]))
    const axis = [...axes].sort((a, b) => span(b) - span(a))[0] ?? "x"
    pool.sort((a, b) => a[axis] - b[axis])
    const middle = Math.ceil(kinds.length / 2),
      cut = kinds.slice(0, middle).reduce((sum, group) => sum + group.length, 0)
    assign(pool.slice(0, cut), kinds.slice(0, middle))
    assign(pool.slice(cut), kinds.slice(middle))
  }
  assign(points, groups)
  const mesh = sphereMesh(stars)
  return { stars, ...mesh, propagation: propagationPlan(stars, mesh.edges) }
}
export type Orbit = {
  yaw: number
  pitch: number
  zoom: number
  roll?: number
  offsetX?: number
  focus?: Vec3
}
/** Turn a chosen node to the front without changing its graph coordinates. */
export function focusOrbit(point: Vec3): Orbit {
  return {
    yaw: -Math.atan2(point.x, point.z),
    pitch: Math.atan2(point.y, Math.hypot(point.x, point.z)),
    zoom: 1,
  }
}
export function rotatePoint(point: Vec3, orbit: Orbit): Vec3 {
  const x = point.x * Math.cos(orbit.yaw) + point.z * Math.sin(orbit.yaw)
  const z = -point.x * Math.sin(orbit.yaw) + point.z * Math.cos(orbit.yaw)
  const y = point.y * Math.cos(orbit.pitch) - z * Math.sin(orbit.pitch)
  const roll = orbit.roll ?? 0
  return {
    x: x * Math.cos(roll) - y * Math.sin(roll),
    y: x * Math.sin(roll) + y * Math.cos(roll),
    z: point.y * Math.sin(orbit.pitch) + z * Math.cos(orbit.pitch),
  }
}
export const edgeLabels: Record<string, string> = {
  related: "关联",
  derived_from: "派生",
  same_subject: "共同对象",
  evidence: "共同证据",
}
