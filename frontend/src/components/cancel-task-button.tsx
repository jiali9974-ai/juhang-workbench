import { useState } from "react"
import { Loader2, X } from "lucide-react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import type { Job } from "@/lib/api"
import { uploadTasks } from "@/lib/upload-tasks"

export function CancelTaskButton({ job }: { job: Job }) {
  const { cancel } = useJobs()
  const [sending, setSending] = useState(false)
  if (job.kind === "request" || (job.status !== "queued" && job.status !== "running")) return null
  const cancelling = sending || job.cancel_requested
  async function stop() {
    if (cancelling) return
    if (job.kind === "upload") {
      uploadTasks.cancel(job.id.slice("upload:".length))
      return
    }
    setSending(true)
    try {
      await cancel(job.id)
    } catch (error) {
      toast.error("取消失败", { description: String(error).replace(/^Error: /, "") })
    } finally {
      setSending(false)
    }
  }
  return (
    <Button size="sm" variant="ghost" className="h-7 shrink-0 gap-1 px-2" disabled={!!cancelling}
      title={cancelling ? "等待当前处理停止" : `取消${job.title}`} aria-label={`取消${job.title}`} onClick={stop}>
      {cancelling ? <Loader2 className="size-3 animate-spin" /> : <X className="size-3" />}
      {cancelling ? "正在取消" : "取消"}
    </Button>
  )
}
