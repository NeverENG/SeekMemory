import { StyleValueInput } from "./style-value"
import { useId, useState } from "react"
import { Button, Input, JsonView, Textarea } from "@/ui"
import type { FieldErrors, PersonaSettings } from "../settings"

export function PersonaFields({
  value,
  onChange,
  errors = {},
  disabled = false,
}: {
  value: PersonaSettings
  onChange: (value: PersonaSettings) => void
  errors?: FieldErrors
  disabled?: boolean
}) {
  const id = useId()
  const [newKey, setNewKey] = useState("")
  const [styleError, setStyleError] = useState("")
  const updateStyle = (key: string, next: PersonaSettings["style"][string]) =>
    onChange({ ...value, style: { ...value.style, [key]: next } })
  return (
    <fieldset disabled={disabled} className="min-w-0 space-y-5">
      <legend className="sr-only">人格设定</legend>
      <label className="block space-y-2" htmlFor={`${id}-name`}>
        <span>姓名</span>
        <Input
          id={`${id}-name`}
          value={value.name}
          maxLength={80}
          aria-invalid={!!errors["name"]}
          aria-describedby={errors["name"] ? `${id}-name-error` : undefined}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
        {errors["name"] && (
          <span
            id={`${id}-name-error`}
            role="alert"
            className="text-sm text-destructive"
          >
            {errors["name"]}
          </span>
        )}
      </label>
      <label className="block space-y-2" htmlFor={`${id}-text`}>
        <span>人格正文</span>
        <Textarea
          id={`${id}-text`}
          rows={8}
          value={value.persona}
          maxLength={20000}
          aria-invalid={!!errors["persona"]}
          aria-describedby={errors["persona"] ? `${id}-text-error` : undefined}
          onChange={(e) => onChange({ ...value, persona: e.target.value })}
        />
        {errors["persona"] && (
          <span
            id={`${id}-text-error`}
            role="alert"
            className="text-sm text-destructive"
          >
            {errors["persona"]}
          </span>
        )}
      </label>
      <section className="min-w-0 space-y-3" aria-label="表达风格">
        <h3 className="font-semibold">表达风格</h3>
        {Object.entries(value.style).map(([key, item]) => (
          <div key={key} className="min-w-0 space-y-2 rounded-lg border p-3">
            <label className="block space-y-2">
              <span className="wrap-anywhere">{key}</span>
              <StyleValueInput
                name={key}
                value={item}
                onChange={(next) => updateStyle(key, next)}
              />
            </label>
            {(item === null || typeof item === "object") && (
              <details>
                <summary>查看高级风格设定</summary>
                <JsonView value={item} />
              </details>
            )}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              aria-label={`移除风格 ${key}`}
              onClick={() => {
                const style = { ...value.style }
                delete style[key]
                onChange({ ...value, style })
              }}
            >
              移除此项
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-2">
          <label
            htmlFor={`${id}-style-key`}
            className="min-w-0 flex-1 space-y-2"
          >
            <span className="text-sm">新增风格名称</span>
            <Input
              id={`${id}-style-key`}
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder="例如：语气、用词偏好"
            />
          </label>
          <Button
            type="button"
            variant="outline"
            onClick={() => {
              const key = newKey.trim()
              if (!key || Object.hasOwn(value.style, key)) {
                setStyleError("请输入尚未使用的风格名称")
                return
              }
              updateStyle(key, "")
              setNewKey("")
              setStyleError("")
            }}
          >
            添加风格
          </Button>
        </div>
        {(styleError || errors["style"]) && (
          <p role="alert" className="text-sm text-destructive">
            {styleError || errors["style"]}
          </p>
        )}
      </section>
      <label className="block space-y-2" htmlFor={`${id}-boundaries`}>
        <span>相处边界（每行一条）</span>
        <Textarea
          id={`${id}-boundaries`}
          rows={4}
          value={value.boundaries.join("\n")}
          aria-invalid={!!errors["boundaries"]}
          onChange={(e) =>
            onChange({
              ...value,
              boundaries: e.target.value ? e.target.value.split("\n") : [],
            })
          }
        />
        {errors["boundaries"] && (
          <span role="alert" className="text-sm text-destructive">
            {errors["boundaries"]}
          </span>
        )}
      </label>
    </fieldset>
  )
}
