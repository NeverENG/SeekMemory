import { useCallback, useEffect, useRef, useState } from "react"
import type { TraceQuery } from "../../contracts/api.ts"
import type { ManagementClient } from "./model.ts"
import {
  filterRuns,
  runTimeline,
  type TraceFlag,
  type TraceSnapshot,
} from "./trace-model.ts"

export function useRunTraces(client: ManagementClient, initialRun = "") {
  const [query, setQuery] = useState<TraceQuery>(
    initialRun ? { run_id: initialRun } : {}
  )
  const [snapshot, setSnapshot] = useState<TraceSnapshot | null>(null)
  const [error, setError] = useState("")
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<TraceFlag | "all">("all")
  const [selected, setSelected] = useState(initialRun)
  const [limit, setLimit] = useState(50)
  const generation = useRef(0)
  const load = useCallback((): Promise<void> => {
    const version = ++generation.current
    return Promise.resolve()
      .then(() => client.traces(query))
      .then((result) => {
        if (version !== generation.current) return
        setSnapshot(result)
        setError("")
      })
      .catch((failure: unknown) => {
        if (version !== generation.current) return
        setError(failure instanceof Error ? failure.message : "轨迹读取失败")
        setSnapshot(null)
      })
      .finally(() => {
        if (version === generation.current) setLoading(false)
      })
  }, [client, query])
  useEffect(() => {
    void load()
    return () => {
      generation.current += 1
    }
  }, [load])
  const refresh = () => {
    setLoading(true)
    setError("")
    return load()
  }
  const runs = snapshot ? filterRuns(snapshot, filter) : []
  const active = runs.find((run) => run.id === selected) ?? runs[0] ?? null
  const timeline = snapshot && active ? runTimeline(snapshot, active.id) : []
  return {
    snapshot,
    applyQuery: (next: TraceQuery) => {
      generation.current += 1
      setLoading(true)
      setError("")
      setSnapshot(null)
      setLimit(50)
      setQuery(next)
    },
    error,
    loading,
    filter,
    setFilter,
    runs: runs.slice(0, limit),
    total: runs.length,
    showMore: () => setLimit((value) => value + 50),
    active,
    timeline,
    select: setSelected,
    refresh,
  }
}
