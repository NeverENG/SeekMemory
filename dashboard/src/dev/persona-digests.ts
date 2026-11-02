import type { PersonaBundle, PersonaSeed } from "../features/shell/model.ts"
import type { ArtifactDetail } from "../features/control/model.ts"
import { applicationSchema } from "../features/control/model.ts"

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value !== null && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, item]) => [key, canonical(item)])
    )
  return value
}
export async function digest(value: unknown): Promise<string> {
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(JSON.stringify(canonical(value)))
  )
  return [...new Uint8Array(bytes)]
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("")
}
export async function artworkDigest(
  bundle: PersonaBundle
): Promise<string | null> {
  if (!bundle.artwork) return null
  const bytes = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(bundle.artwork.dataBase64)
  )
  return [...new Uint8Array(bytes)]
    .map((n) => n.toString(16).padStart(2, "0"))
    .join("")
}
export const settingsDigest = (seed: PersonaSeed) =>
  digest({
    name: seed.name,
    text: seed.persona,
    style: seed.style ?? {},
    boundaries: seed.boundaries ?? [],
  })
export async function applicationView(
  payload: ArtifactDetail["artifact"]["payload"]
) {
  const raw = payload["pack_application"]
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null
  const result = applicationSchema.safeParse({
    reference: raw["reference"],
    version: raw["version"],
    packDigest: raw["pack_digest"],
    settingsDigest: raw["settings_digest"],
    artworkDigest: raw["artwork_digest"],
    currentSettingsDigest: await digest({
      name: payload["persona_name"] ?? "",
      text: payload["text"] ?? "",
      style: payload["style"] ?? {},
      boundaries: payload["boundaries"] ?? [],
    }),
  })
  return result.success ? result.data : null
}
