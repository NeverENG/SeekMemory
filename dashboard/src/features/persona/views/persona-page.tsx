import { CurrentArtwork } from "./current-artwork"
import { PersonaEditor } from "./persona-editor"
import { RollbackPanel } from "./rollback-panel"
import { VersionDiff } from "./version-diff"
import { useState } from "react"
import { ArrowUpRight, History, PenLine } from "lucide-react"
import { Badge, Button, DetailDrawer } from "@/ui"
import type { ManagementClient, RuntimeStatus } from "@/features/control/model"
import { PersonaEvidence } from "@/features/control/views/persona-evidence"
import { PageIntro, formatDate } from "@/features/shell/page-parts"
export function PersonaPage({
  client,
  status,
  revision,
  onInspect,
  studio = false,
  onSaved,
}: {
  client: ManagementClient
  status: RuntimeStatus | null
  revision: number | null
  onInspect: (id: string) => void
  onSaved: () => Promise<void>
  studio?: boolean
}) {
  const persona = status?.persona
  const [selected, setSelected] = useState<number | null>(revision)
  const [evidence, setEvidence] = useState(false)
  const [editing, setEditing] = useState(false)
  const revisions = [...(persona?.revisions ?? [])].sort(
    (a, b) => b.revision - a.revision
  )
  const active = revisions.find((r) => r.revision === selected)
  const previous = active
    ? revisions.find((r) => r.revision === active.revision - 1)
    : null
  return (
    <div className="console-page">
      <PageIntro title={studio ? "人格工作室" : "成长时间线"} />
      {!persona ? (
        <div className="console-empty">
          <History size={28} />
          <h2>人格故事还没有开始</h2>
          <p>选择一个初始人格，或等待记忆沉淀出第一版人格。</p>
          <a className="console-link" href="#/store">
            浏览人格商店 <ArrowUpRight size={15} />
          </a>
        </div>
      ) : (
        <>
          {studio && (
            <section className="console-panel mb-8 p-6">
              <div className="flex items-center justify-between">
                <h2 className="text-lg font-semibold">当前人格</h2>
                <Badge>第 {persona.revision} 版</Badge>
              </div>
              <div className="my-4 flex items-center gap-4">
                <CurrentArtwork
                  client={client.console}
                  persona={persona}
                  className="h-24 w-24 shrink-0 rounded-xl object-contain"
                />
                <div className="min-w-0 text-sm">
                  <p>{persona.name || "当前人格"}</p>
                  <p className="wrap-anywhere text-muted-foreground">
                    {persona.packApplication
                      ? `基于${persona.packApplication.reference.startsWith("official/") ? "官方包" : "个人包"} ${persona.packApplication.reference.split("/")[1]} · ${persona.packApplication.currentSettingsDigest === persona.packApplication.settingsDigest ? "设定与应用时一致" : "当前设定已变化"}`
                      : "包来源不确定"}
                  </p>
                </div>
              </div>
              <p className="my-6 leading-8 whitespace-pre-wrap">
                {persona.text}
              </p>
              <Button
                disabled={!status?.ready || !!status.activeTask}
                onClick={() => setEditing(true)}
              >
                <PenLine size={15} />
                编辑当前人格
              </Button>
              <Button variant="ghost" onClick={() => onInspect(persona.id)}>
                高级编辑与审计
              </Button>
              <p className="mt-3 text-xs text-muted-foreground">
                编辑会新增版本。需要恢复旧设定时，请在下方选择历史版本并核对差异。
              </p>
            </section>
          )}
          {editing && (
            <PersonaEditor
              key={persona.id}
              client={client}
              id={persona.id}
              blocked={!status?.ready || !!status.activeTask}
              onClose={() => setEditing(false)}
              onSaved={onSaved}
            />
          )}
          <div className="persona-timeline">
            {revisions.map((item) => (
              <button
                type="button"
                className="persona-revision"
                key={item.revision}
                onClick={() => {
                  setSelected(item.revision)
                  setEvidence(false)
                }}
              >
                <span className="revision-dot" />
                <div className="revision-date">
                  {formatDate(item.at)}
                  <span>第 {item.revision} 版</span>
                </div>
                <div className="console-panel revision-body">
                  <div className="flex items-center justify-between gap-3">
                    <Badge variant="secondary">
                      {item.revision === persona.revision
                        ? "当前版本"
                        : "历史版本"}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {item.op}
                    </span>
                  </div>
                  <p className="line-clamp-3">{item.text}</p>
                  {item.changeReason && (
                    <p className="text-sm text-muted-foreground">
                      变化原因：{item.changeReason}
                    </p>
                  )}
                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>
                      {item.sourceIds.length} 条来源 · {item.derivedFrom.length}{" "}
                      条派生记忆
                    </span>
                    <ArrowUpRight size={16} />
                  </div>
                </div>
              </button>
            ))}
          </div>
          <DetailDrawer
            open={!!active}
            onOpenChange={(open) => {
              if (!open) {
                setSelected(null)
                setEvidence(false)
              }
            }}
            title={`人格第 ${active?.revision ?? ""} 版`}
            description="版本正文、前后变化与来源"
          >
            <div className="space-y-6 p-6">
              <p className="leading-8 whitespace-pre-wrap">{active?.text}</p>
              {active?.changeReason && (
                <p className="text-sm">变化原因：{active.changeReason}</p>
              )}
              {previous && (
                <details className="rounded-xl border p-4">
                  <summary>对照上一版</summary>
                  <VersionDiff
                    before={previous.text}
                    after={active?.text ?? ""}
                  />
                </details>
              )}
              {active &&
                active.revision !== persona.revision &&
                client.console && (
                  <RollbackPanel
                    key={`${persona.id}-${active.revision}`}
                    client={client.console}
                    id={persona.id}
                    revision={active.revision}
                    currentText={persona.text}
                    targetText={active.text}
                    blocked={!status?.ready || !!status.activeTask}
                    onSaved={onSaved}
                  />
                )}
              <p className="text-xs text-muted-foreground">
                来源正文仅在主动检查时读取。
              </p>
              <Button variant="outline" onClick={() => setEvidence(!evidence)}>
                {evidence ? "收起来源" : "检查受保护的来源"}
              </Button>
              {evidence && active && (
                <PersonaEvidence
                  key={active.revision}
                  client={client}
                  persona={{
                    ...persona,
                    revision: active.revision,
                    revisions: persona.revisions.filter(
                      (r) => r.revision === active.revision
                    ),
                  }}
                />
              )}
            </div>
          </DetailDrawer>
        </>
      )}
    </div>
  )
}
