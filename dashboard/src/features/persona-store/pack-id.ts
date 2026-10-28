/** getRandomValues also works on ordinary LAN HTTP; randomUUID requires HTTPS. */
export function newPackId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return `my-${Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("")}`
}
