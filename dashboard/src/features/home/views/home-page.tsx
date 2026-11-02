import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowUpRight, Pause, Play } from "lucide-react"
import { Button } from "@/ui"
import avatar from "@/assets/ds-chibi-head.webp"
import type { ManagementClient, RuntimeStatus } from "@/features/control/model"
import { useResource } from "@/features/shell/use-resource"
import { formatDate, ResourceState } from "@/features/shell/page-parts"
export function HomePage({
  client,
  status,
  loading,
}: {
  client: ManagementClient
  status: RuntimeStatus | null
  loading: boolean
}) {
  const persona = status?.persona
  const [paused, setPaused] = useState(false)
  const read = useCallback(() => client.traces(), [client])
  const feed = useResource(read)
  const refreshFeed = feed.reload
  const terminal = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (paused) return
    const timer = setInterval(() => {
      void refreshFeed()
    }, 15000)
    return () => clearInterval(timer)
  }, [paused, refreshFeed])
  useEffect(() => {
    if (!paused) terminal.current?.scrollTo({ top: 0 })
  }, [feed.data, paused])
  const milestones = [...(persona?.revisions ?? [])]
    .sort((a, b) => b.revision - a.revision)
    .slice(0, 3)
  return (
    <div className="console-home">
      <section className="persona-stage">
        <img
          src={avatar}
          alt="蓝发 Q 版角色正面趴在桌边，下巴和两只圆手搭着桌沿"
          className="stage-avatar"
        />
        <div className="stage-copy">
          <h1>让记忆，慢慢成为自己。</h1>
          <p className="line-clamp-3">
            {loading
              ? "正在读取当前人格…"
              : persona?.text || "选择一个初始人格，开始积累记忆。"}
          </p>
          <a
            className="console-hero-action"
            href={persona ? "#/studio" : "#/store"}
          >
            {persona ? "打理当前人格" : "选择初始人格"}
            <ArrowUpRight size={16} />
          </a>
        </div>
      </section>
      <div className="console-home-grid">
        <section className="console-panel event-terminal">
          <div className="console-panel-heading">
            <div>
              <h2>运行事件</h2>
            </div>
            <Button
              variant="ghost"
              size="icon"
              title={paused ? "继续更新事件" : "每 15 秒更新，点击暂停"}
              aria-label={paused ? "继续更新事件" : "暂停更新事件"}
              onClick={() => setPaused(!paused)}
            >
              {paused ? <Play size={16} /> : <Pause size={16} />}
            </Button>
          </div>
          <div className="terminal-rows" ref={terminal}>
            <ResourceState
              loading={feed.loading && !feed.data}
              error={feed.error}
              empty={feed.data?.runs.length === 0}
              onRetry={feed.reload}
            />
            {feed.data?.runs.slice(0, 50).map((run) => (
              <a
                className="terminal-row"
                key={run.id}
                href={`#/system?section=traces&node=${encodeURIComponent(run.id)}`}
              >
                <span className="terminal-dot" />
                <div>
                  <span className="text-xs text-muted-foreground">
                    {formatDate(run.started_at)}
                  </span>
                  <p>
                    {run.delivered
                      ? "一条回复已送达"
                      : `运行${run.status === "error" ? "发生错误" : "已记录"}`}
                  </p>
                  <span className="text-xs text-muted-foreground">
                    {run.event_count} 个步骤
                  </span>
                </div>
                <ArrowUpRight size={14} />
              </a>
            ))}
          </div>
          <a href="#/system?section=traces" className="terminal-footer">
            查看完整运行轨迹 <ArrowUpRight size={14} />
          </a>
        </section>
        <section className="console-panel home-history">
          <div className="console-panel-heading">
            <div>
              <h2>成长的足迹</h2>
            </div>
            <a className="console-link" href="#/persona">
              全部版本 <ArrowUpRight size={14} />
            </a>
          </div>
          <div className="milestone-grid">
            {milestones.map((item) => (
              <a
                href={`#/persona?revision=${item.revision}`}
                key={item.revision}
                className="milestone"
              >
                <span className="text-xs text-muted-foreground">
                  {formatDate(item.at)} · 第 {item.revision} 版
                </span>
                <p className="line-clamp-2">{item.text}</p>
                <span className="text-xs text-muted-foreground">
                  {item.sourceIds.length} 条来源记录
                </span>
              </a>
            ))}
            {!milestones.length && (
              <p className="p-6 text-sm text-muted-foreground">
                第一次人格记录，会从这里开始。
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
