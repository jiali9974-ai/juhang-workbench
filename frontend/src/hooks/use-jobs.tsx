import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { toast } from "sonner"

import { api, type Job } from "@/lib/api"

type Callback = (job: Job) => void

interface JobsCtx {
  jobs: Job[]
  active: Job[]
  /** 跟踪一个任务，完成时回调；出错会自动弹提示 */
  watch: (job: Job, onDone?: Callback) => void
  /** 任意任务结束时自增，页面用它来刷新数据 */
  version: number
}

const Ctx = createContext<JobsCtx | null>(null)

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [version, setVersion] = useState(0)
  const callbacks = useRef(new Map<string, Callback | undefined>())
  const seenFinished = useRef(new Set<string>())

  const poll = useCallback(async () => {
    let list: Job[]
    try {
      list = await api.jobs()
    } catch {
      return
    }
    setJobs(list)
    let finishedNow = false
    for (const j of list) {
      const over = j.status === "done" || j.status === "error"
      if (over && !seenFinished.current.has(j.id)) {
        seenFinished.current.add(j.id)
        finishedNow = true
        if (callbacks.current.has(j.id)) {
          const cb = callbacks.current.get(j.id)
          callbacks.current.delete(j.id)
          if (j.status === "done") cb?.(j)
          else toast.error(`${j.title} 出错`, { description: j.error.split("\n")[0] })
        }
      }
    }
    if (finishedNow) setVersion((v) => v + 1)
  }, [])

  useEffect(() => {
    // 页面打开前就已经结束的任务不再回调
    api.jobs().then((list) => {
      list.filter((j) => j.status === "done" || j.status === "error").forEach((j) => seenFinished.current.add(j.id))
      setJobs(list)
    }).catch(() => {})
    const t = setInterval(poll, 1500)
    return () => clearInterval(t)
  }, [poll])

  const watch = useCallback((job: Job, onDone?: Callback) => {
    callbacks.current.set(job.id, onDone)
    poll()
  }, [poll])

  const active = jobs.filter((j) => j.status === "queued" || j.status === "running")
  return <Ctx.Provider value={{ jobs, active, watch, version }}>{children}</Ctx.Provider>
}

export function useJobs() {
  const c = useContext(Ctx)
  if (!c) throw new Error("useJobs 必须在 JobsProvider 里用")
  return c
}
