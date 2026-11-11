import { Fragment, useState } from "react"
import { systemSections } from "@/features/control/sections"
import {
  BookOpen,
  ChevronDown,
  Fish,
  History,
  House,
  Moon,
  Orbit,
  PanelLeftClose,
  PanelLeftOpen,
  RefreshCw,
  Settings,
  SlidersHorizontal,
  Store,
  Users,
} from "lucide-react"
import { Button } from "@/ui"
import type { WorkspacePage } from "./model"

const groups = [
  {
    label: "工作空间",
    pages: [
      { id: "home", label: "首页", icon: House },
      { id: "persona", label: "成长时间线", icon: History },
      { id: "memory", label: "记忆星图", icon: Orbit },
      { id: "library", label: "记忆库", icon: BookOpen },
      { id: "impressions", label: "人物印象", icon: Users },
    ],
  },
  {
    label: "人格管理",
    pages: [
      { id: "studio", label: "人格工作室", icon: SlidersHorizontal },
      { id: "store", label: "人格小铺", icon: Store },
    ],
  },
  {
    label: "运行管理",
    pages: [
      { id: "dream", label: "Dream 日志", icon: Moon },
      { id: "system", label: "系统", icon: Settings },
    ],
  },
] as const

export function Sidebar({
  page,
  section,
  collapsed,
  onToggle,
  ready,
  loading,
  onRefresh,
}: {
  page: WorkspacePage
  section?: string | undefined
  collapsed: boolean
  onToggle: () => void
  ready: boolean
  loading: boolean
  onRefresh: () => void
}) {
  const [hiddenForSection, setHiddenForSection] = useState<string | null>(null)
  const activeSection =
    systemSections.find((item) => item.id === section)?.id ?? "runtime"
  const systemOpen = page === "system" && hiddenForSection !== activeSection
  return (
    <aside className="console-sidebar" aria-label="侧边栏">
      <a
        href="#/home"
        className="console-brand"
        aria-label="SeekMemory 首页"
        title="SeekMemory 首页"
      >
        <span>
          <Fish size={23} aria-hidden="true" />
        </span>
        <div className="sidebar-label">SeekMemory</div>
      </a>
      <nav aria-label="控制台导航">
        {groups.map((group) => (
          <section
            className="sidebar-group"
            key={group.label}
            aria-label={group.label}
          >
            {group.pages.map(({ id, label, icon: Icon }) => (
              <Fragment key={id}>
                {id === "system" ? (
                  <button
                    type="button"
                    className="sidebar-system-toggle"
                    aria-label="系统"
                    title="系统"
                    aria-expanded={systemOpen}
                    aria-controls="system-submenu"
                    data-active={page === "system"}
                    onClick={() => {
                      if (page !== "system") {
                        setHiddenForSection(null)
                        window.location.hash = "/system?section=runtime"
                      } else
                        setHiddenForSection(systemOpen ? activeSection : null)
                    }}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span className="sidebar-label">{label}</span>
                    <ChevronDown
                      size={14}
                      className={`sidebar-chevron ${systemOpen ? "is-open" : ""}`}
                      aria-hidden="true"
                    />
                  </button>
                ) : (
                  <a
                    href={`#/${id}`}
                    aria-label={label}
                    title={label}
                    aria-current={page === id ? "page" : undefined}
                  >
                    <Icon size={18} aria-hidden="true" />
                    <span className="sidebar-label">{label}</span>
                  </a>
                )}
                {id === "system" && systemOpen && (
                  <div
                    id="system-submenu"
                    className="sidebar-submenu"
                    role="group"
                    aria-label="系统功能"
                  >
                    {systemSections.map(
                      ({ id: childId, label: childLabel, icon: ChildIcon }) => (
                        <a
                          key={childId}
                          href={`#/system?section=${childId}`}
                          aria-label={childLabel}
                          title={childLabel}
                          aria-current={
                            activeSection === childId ? "page" : undefined
                          }
                        >
                          <ChildIcon size={16} aria-hidden="true" />
                          <span className="sidebar-label">{childLabel}</span>
                        </a>
                      )
                    )}
                  </div>
                )}
              </Fragment>
            ))}
          </section>
        ))}
      </nav>
      <div className="sidebar-bottom">
        <div
          className="sidebar-status"
          title={ready ? "记忆引擎已连接" : "记忆引擎未就绪"}
        >
          <span
            className={`sidebar-status-dot ${ready ? "is-ready" : ""}`}
            aria-hidden="true"
          />
          <span className="sidebar-label">{ready ? "已连接" : "未就绪"}</span>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="刷新控制台"
            title="刷新控制台"
            disabled={loading}
            onClick={onRefresh}
          >
            <RefreshCw size={15} />
          </Button>
        </div>
        <Button
          className="sidebar-collapse"
          variant="ghost"
          onClick={onToggle}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          aria-expanded={!collapsed}
          title={collapsed ? "展开侧边栏" : "收起侧边栏"}
        >
          {collapsed ? (
            <PanelLeftOpen size={18} />
          ) : (
            <PanelLeftClose size={18} />
          )}
          <span className="sidebar-label">收起侧边栏</span>
        </Button>
      </div>
    </aside>
  )
}
