import type { components, operations } from "./generated.ts"

export type ApiSchemas = components["schemas"]
export type ApiResponse<K extends keyof operations> =
  operations[K]["responses"][200]["content"]["application/json"]
export type ApiRequest<
  K extends
    | "update"
    | "diagnose"
    | "task"
    | "cancel"
    | "persona"
    | "rollbackPersona",
> = operations[K]["requestBody"]["content"]["application/json"]

export type TraceQuery = NonNullable<
  operations["traces"]["parameters"]["query"]
>

// 传输类型可变，记忆领域投影保持深层只读；不将 UI 状态写入生成契约。
export type DeepReadonly<T> = {
  readonly [K in keyof T]: T[K] extends object ? DeepReadonly<T[K]> : T[K]
}
