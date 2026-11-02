import { Input, Textarea } from "@/ui"
import type { PersonaSettings } from "../settings"

type StyleValue = PersonaSettings["style"][string]
export function StyleValueInput({
  name,
  value,
  onChange,
}: {
  name: string
  value: StyleValue
  onChange: (value: StyleValue) => void
}) {
  if (typeof value === "string")
    return (
      <Textarea
        aria-label={`风格 ${name}`}
        rows={2}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    )
  if (typeof value === "number")
    return (
      <Input
        aria-label={`风格 ${name}`}
        type="number"
        value={value}
        onChange={(e) => {
          if (e.target.value !== "" && Number.isFinite(Number(e.target.value)))
            onChange(Number(e.target.value))
        }}
      />
    )
  if (typeof value === "boolean")
    return (
      <input
        aria-label={`风格 ${name}`}
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
      />
    )
  return (
    <span className="block text-sm text-muted-foreground">
      此项包含结构化设定，将完整保留。高级内容见下方。
    </span>
  )
}
