import { bundleSchema, seedSchema, type PersonaBundle } from "../shell/model.ts"

export const MAX_PACK_BYTES = 3 * 1024 * 1024
export const MAX_ARTWORK_BYTES = 2 * 1024 * 1024

export function parsePackFile(text: string): PersonaBundle {
  if (new TextEncoder().encode(text).length > MAX_PACK_BYTES)
    throw new Error("人格包不能超过 3 MiB")
  const value: unknown = JSON.parse(text)
  if (typeof value === "object" && value !== null && "format" in value)
    return bundleSchema.parse(value)
  if (new TextEncoder().encode(text).length > 65536)
    throw new Error("纯设定 JSON 不能超过 64 KiB")
  return {
    format: "seekmemory.persona-pack/v1",
    seed: seedSchema.parse(value),
    licenseText: "",
    artwork: null,
  }
}

export async function readArtwork(
  file: File
): Promise<NonNullable<PersonaBundle["artwork"]>> {
  if (file.size === 0 || file.size > MAX_ARTWORK_BYTES)
    throw new Error("封面需要是 2 MiB 以内的 PNG")
  const bytes = new Uint8Array(await file.arrayBuffer())
  const signature = [137, 80, 78, 71, 13, 10, 26, 10]
  if (!signature.every((value, index) => bytes[index] === value))
    throw new Error("封面仅支持 PNG；请先将图片导出为 PNG")
  let binary = ""
  for (let i = 0; i < bytes.length; i += 8192)
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
  return { mediaType: "image/png", dataBase64: btoa(binary) }
}

export function downloadPack(value: unknown, filename: string): void {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" })
  )
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
