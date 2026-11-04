import { Input, Textarea } from "@/ui"
import type { PersonaBundle } from "@/features/shell/model"
import type { FieldErrors } from "@/features/persona/settings"

export function PackMetadataFields({
  pack,
  onChange,
  errors,
}: {
  pack: PersonaBundle
  onChange: (pack: PersonaBundle) => void
  errors: FieldErrors
}) {
  return (
    <div className="space-y-4">
      {(
        [
          ["id", "包标识", 64],
          ["version", "新包版本", 32],
          ["license", "许可证名称", 200],
          ["source", "设定与封面来源", 200],
          ["content_rating", "内容分级", 32],
          ["locale", "语言", 20],
        ] as const
      ).map(([key, label, maxLength]) => (
        <label className="block space-y-2" key={key}>
          <span>{label}</span>
          <Input
            value={pack.seed[key] ?? ""}
            maxLength={maxLength}
            aria-invalid={!!errors[key]}
            onChange={(e) =>
              onChange({
                ...pack,
                seed: { ...pack.seed, [key]: e.target.value },
              })
            }
          />
          {errors[key] && (
            <span role="alert" className="text-sm text-destructive">
              {errors[key]}
            </span>
          )}
        </label>
      ))}
      <label className="block space-y-2">
        <span>许可证正文（有封面时必填）</span>
        <Textarea
          rows={5}
          value={pack.licenseText}
          aria-invalid={!!errors["licenseText"]}
          onChange={(e) => onChange({ ...pack, licenseText: e.target.value })}
        />
        {errors["licenseText"] && (
          <span role="alert" className="text-sm text-destructive">
            {errors["licenseText"]}
          </span>
        )}
      </label>
    </div>
  )
}
