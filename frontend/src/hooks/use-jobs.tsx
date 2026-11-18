import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react"
import { toast } from "sonner"

import { api, type Job } from "@/lib/api"

type Callback = (job: Job) => void

interface JobsCtx {
  jobs: Job[]
  active: Job[]
  /** 跟踪一个任务，完成时回调；出错会自动弹提示 */
  watch: (job: Job, onDone?: Callback) => void
  cancel: (id: string) => Promise<void>
  /** 任意任务结束时自增，页面用它来刷新数据 */
  version: number
}

const Ctx = createContext<JobsCtx | null>(null)

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([])
  const [version, setVersion] = useState(0)
  const callbacks = useRef(new Map<string, Callback | undefined>())
  const seenFinished = useRef(new Set<string>())
  const initialized = useRef(false)
  const polling = useRef<Promise<void> | null>(null)
  const optimistic = useRef(new Map<string, number>())

  const poll = useCallback(() => {
    if (polling.current) return polling.current
    const update = async () => {
      let list: Job[]
      try {
        list = await api.jobs()
      } catch {
        return
      }
      const returned = new Set(list.map((job) => job.id))
      for (const id of returned) optimistic.current.delete(id)
      setJobs((previous) => [...list, ...previous.filter((job) => !returned.has(job.id) && Date.now() - (optimistic.current.get(job.id) ?? 0) < 10000)])
      let finishedNow = false
      for (const j of list) {
        const over = j.status === "done" || j.status === "error" || j.status === "cancelled"
        if (over && !seenFinished.current.has(j.id)) {
          seenFinished.current.add(j.id)
          finishedNow = initialized.current || callbacks.current.has(j.id) || finishedNow
          if (callbacks.current.has(j.id)) {
            const cb = callbacks.current.get(j.id)
            callbacks.current.delete(j.id)
            if (j.status === "done") {
              try { cb?.(j) } catch { /* 不让页面回调影响其余任务的轮询。 */ }
            }
            else if (j.status === "error") toast.error(`${j.title} 出错`, { description: j.error.split("\n")[0] })
          }
        }
      }
      if (finishedNow) setVersion((v) => v + 1)
      initialized.current = true
    }
    const request = update().finally(() => { polling.current = null })
    polling.current = request
    return request
  }, [])

  useEffect(() => {
    poll()
    const t = setInterval(poll, 1500)
    const visible = () => { if (document.visibilityState === "visible") poll() }
    document.addEventListener("visibilitychange", visible)
    window.addEventListener("focus", poll)
    return () => {
      clearInterval(t)
      document.removeEventListener("visibilitychange", visible)
      window.removeEventListener("focus", poll)
    }
  }, [poll])

  const watch = useCallback((job: Job, onDone?: Callback) => {
    callbacks.current.set(job.id, onDone)
    optimistic.current.set(job.id, Date.now())
    setJobs((previous) => [job, ...previous.filter((item) => item.id !== job.id)])
    poll()
  }, [poll])

  const active = jobs.filter((j) => j.status === "queued" || j.status === "running")
  const cancel = useCallback(async (id: string) => {
    const job = await api.cancelJob(id)
    // 先等已发出的轮询结束，避免旧响应把“正在取消”覆盖回运行中。
    await polling.current
    setJobs((previous) => previous.map((item) => item.id === id ? job : item))
    await poll()
  }, [poll])
  return <Ctx.Provider value={{ jobs, active, watch, cancel, version }}>{children}</Ctx.Provider>
}

export function useJobs() {
  const c = useContext(Ctx)
  if (!c) throw new Error("useJobs 必须在 JobsProvider 里用")
  return c
}
