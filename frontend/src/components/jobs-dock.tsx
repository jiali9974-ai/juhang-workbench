import { useState } from "react"
import { CheckCircle2, ChevronUp, CircleAlert, Loader2 } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"

import { ease } from "@/components/motion"
import { useTaskList } from "@/hooks/use-task-list"
import { cn } from "@/lib/utils"

const STATE = { queued: "排队", running: "", done: "完成", error: "出错" } as const

export function JobsDock({ hideCompleted = false }: { hideCompleted?: boolean }) {
  const { jobs, active } = useTaskList()
  const [open, setOpen] = useState(false)
  const busy = active.length > 0
  return (
    <AnimatePresence>
      {jobs.length > 0 && (!hideCompleted || busy) && (
        <motion.div
          layout
          initial={{ opacity: 0, y: 24, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 24 }}
          transition={{ type: "spring", stiffness: 320, damping: 30 }}
          className="fixed right-5 bottom-5 z-40 max-lg:bottom-24 w-[340px] overflow-hidden rounded-2xl border bg-popover/95 lift-shadow backdrop-blur"
        >
          <motion.button layout="position" className="flex w-full items-center gap-2.5 px-4 py-3 text-left text-[13px] hover:bg-muted/50" onClick={() => setOpen(!open)}>
            <AnimatePresence mode="wait" initial={false}>
              <motion.span key={busy ? "busy" : "idle"} initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.5, opacity: 0 }}>
                {busy ? <Loader2 className="size-4 animate-spin text-gold-ink" /> : <CheckCircle2 className="size-4 text-ok" />}
              </motion.span>
            </AnimatePresence>
            <span className="flex-1 font-medium">{busy ? `${active.length} 个任务进行中` : "任务都完成了"}</span>
            {busy && !open && <span className="max-w-[120px] truncate text-xs text-muted-foreground">{active[0].message}</span>}
            <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.25, ease }}>
              <ChevronUp className="size-4 text-muted-foreground" />
            </motion.span>
          </motion.button>
          {/* 收起时顶部的细进度条 */}
          {busy && !open && (
            <div className="h-0.5 bg-muted">
              <motion.div className={cn("h-full bg-primary", active[0].kind === "request" && "animate-pulse")} animate={{ width: active[0].kind === "request" ? "33%" : `${Math.round(active[0].progress * 100)}%` }} transition={{ duration: 0.5, ease }} />
            </div>
          )}
          <AnimatePresence initial={false}>
            {open && (
              <motion.div
                key="list"
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: "auto", opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.3, ease }}
                className="scrollbar-thin max-h-72 overflow-y-auto border-t"
              >
                <AnimatePresence initial={false}>
                  {[...active, ...jobs.filter((job) => job.status !== "running" && job.status !== "queued")].slice(0, Math.max(12, active.length)).map((j) => (
                    <motion.div
                      key={j.id}
                      layout
                      initial={{ opacity: 0, x: 12 }}
                      animate={{ opacity: 1, x: 0 }}
                      className="border-b border-border/70 px-4 py-2.5 last:border-0"
                    >
                      <div className="flex items-center gap-2 text-[13px]">
                        {j.status === "error" && <CircleAlert className="size-3.5 text-destructive" />}
                        {j.status === "done" && <CheckCircle2 className="size-3.5 text-ok" />}
                        <span className="flex-1 truncate">{j.title}</span>
                        <span className="text-xs text-muted-foreground tabular">
                          {j.kind === "request" ? "进行中" : j.status === "running" ? `${Math.round(j.progress * 100)}%` : STATE[j.status]}
                        </span>
                      </div>
                      <div className={cn("mt-0.5 truncate text-xs", j.status === "error" ? "text-destructive" : "text-muted-foreground")}>
                        {j.status === "error" ? j.error.split("\n")[0] : j.message}
                      </div>
                      <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-muted">
                        <motion.div
                          className={cn("h-full rounded-full", j.status === "done" ? "bg-ok" : j.status === "error" ? "bg-destructive" : "bg-primary")}
                          initial={false}
                          animate={{ width: j.kind === "request" ? "33%" : `${j.status === "done" ? 100 : Math.round(j.progress * 100)}%` }}
                          transition={{ duration: 0.5, ease }}
                        />
                      </div>
                    </motion.div>
                  ))}
                </AnimatePresence>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
