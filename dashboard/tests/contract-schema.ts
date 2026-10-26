import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { Ajv2020 } from "ajv/dist/2020.js"
import { fullFormats } from "ajv-formats/dist/formats.js"
import { parse } from "yaml"
import { z } from "zod"

const contentSchema = z.object({
  content: z.record(
    z.string(),
    z.object({ schema: z.record(z.string(), z.json()) })
  ),
})
const raw: unknown = parse(
  readFileSync(new URL("../../openapi.yaml", import.meta.url), "utf8")
)
const document = z
  .object({
    components: z.record(z.string(), z.json()),
    paths: z.record(
      z.string(),
      z.record(
        z.string(),
        z.object({
          operationId: z.string(),
          responses: z.record(z.string(), contentSchema),
          requestBody: contentSchema.optional(),
        })
      )
    ),
  })
  .parse(raw)

export const apiOperations = Object.values(document.paths).flatMap((path) =>
  Object.values(path)
)
const ajv = new Ajv2020({
  strict: false,
  allErrors: true,
  formats: fullFormats,
})

/** 根据 YAML 中的操作选择正文契约；status=0 表示请求，其他值为响应状态码。 */
export function validateApi(
  action: string,
  status: number,
  data: unknown
): void {
  const operation = apiOperations.find((item) => item.operationId === action)
  assert.ok(operation, `契约中缺少操作：${action}`)
  const body =
    status === 0
      ? operation.requestBody
      : (operation.responses[String(status)] ?? operation.responses["default"])
  assert.ok(body, `契约中缺少正文：${action}/${status}`)
  const content = body.content["application/json"]
  assert.ok(content, `契约中没有 JSON 正文：${action}/${status}`)
  const validate = ajv.compile<unknown>({
    ...content.schema,
    components: document.components,
  })
  assert.equal(
    validate(data),
    true,
    `${action}/${status}: ${ajv.errorsText(validate.errors)}`
  )
}
