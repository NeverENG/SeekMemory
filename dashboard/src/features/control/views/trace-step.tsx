import { Badge } from "@/ui"
import type { TraceEvent } from "../trace-model"

export const eventLabels: Record<TraceEvent["event"], string> = {
  agent_begin: "Agent 开始",
  llm_request: "准备模型请求",
  llm_response: "模型已响应",
  agent_done: "Agent 结束",
  message_sent: "回复已发送",
  tool_call: "开始调用工具",
  tool_result: "工具已返回",
}
const disclosureLabels = {
  full: "全文",
  paraphrase: "改述",
  hint: "提示",
  silence: "隐藏",
}

function ArtifactLinks({
  ids,
  onInspect,
}: {
  ids: readonly string[]
  onInspect: (id: string) => void
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {ids.map((id) => (
        <button
          key={id}
          className="max-w-full text-left font-mono text-xs break-all text-primary underline"
          onClick={() => onInspect(id)}
        >
          {id}
        </button>
      ))}
    </div>
  )
}

export function TraceStep({
  event,
  onInspect,
}: {
  event: TraceEvent
  onInspect: (id: string) => void
}) {
  const recall = event.recall
  return (
    <li className="relative border-l-2 border-primary/20 pb-7 pl-5 last:pb-0">
      <span className="absolute top-1.5 -left-1.5 size-2.5 rounded-full bg-primary" />
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">{eventLabels[event.event]}</h3>
        {event.status === "error" && <Badge tone="danger">失败</Badge>}
        {event.request_index > 0 && (
          <span className="text-xs text-muted-foreground">
            请求 {event.request_index}
          </span>
        )}
        <time className="text-xs text-muted-foreground">
          {new Date(event.at).toLocaleTimeString()}
        </time>
        {event.duration_ms !== null && (
          <span className="text-xs text-muted-foreground">
            {Math.round(event.duration_ms)} ms
          </span>
        )}
      </div>
      {event.tool && (
        <p className="mt-2 text-sm break-all">
          工具：{event.tool}
          {event.event === "tool_result" && " · 已返回，成功与否未判定"}
        </p>
      )}
      {recall && (
        <div className="mt-3 space-y-3 text-sm">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">候选 {recall.candidates}</Badge>
            <Badge variant="secondary">选中 {recall.picked_ids.length}</Badge>
            <Badge variant="secondary">常驻 {recall.pinned_ids.length}</Badge>
            <Badge tone="success">
              注入 {recall.artifact_ids.length} 条 · {recall.chars} 字
            </Badge>
            {recall.withheld_ids.length > 0 && (
              <Badge tone="warning">隐藏 {recall.withheld_ids.length} 条</Badge>
            )}
            {recall.fallback && <Badge tone="info">使用兜底</Badge>}
          </div>
          <ArtifactLinks ids={recall.artifact_ids} onInspect={onInspect} />
          <details className="rounded-lg border p-3">
            <summary className="cursor-pointer text-muted-foreground">
              筛选与披露详情
            </summary>
            <div className="mt-3 space-y-3">
              <p>
                {recall.gate.evaluated
                  ? `相关性检查：通过 ${recall.gate.passed} 条，过滤 ${recall.gate.rejected} 条，阈值 ${recall.gate.threshold.toFixed(2)}`
                  : "本次未执行相关性检查"}
              </p>
              {recall.dropped_ids.length > 0 && (
                <div>
                  <p className="mb-1">组装时未保留</p>
                  <ArtifactLinks
                    ids={recall.dropped_ids}
                    onInspect={onInspect}
                  />
                </div>
              )}
              {Object.entries(recall.disclosure).map(([id, level]) => (
                <div key={id} className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">{disclosureLabels[level]}</Badge>
                  <ArtifactLinks ids={[id]} onInspect={onInspect} />
                </div>
              ))}
            </div>
          </details>
        </div>
      )}
    </li>
  )
}
