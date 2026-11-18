import { Activity, FlaskConical, ListTree, ScrollText } from "lucide-react"

export const systemSections = [
  { id: "runtime", label: "运行与任务", icon: Activity },
  { id: "diagnose", label: "召回诊断", icon: FlaskConical },
  { id: "logs", label: "生命周期日志", icon: ScrollText },
  { id: "traces", label: "运行轨迹", icon: ListTree },
] as const
