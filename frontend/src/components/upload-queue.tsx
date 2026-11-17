import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react"
import { Check, CircleAlert, FileVideo, Loader2, UploadCloud, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { fmtSize, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { uploadTasks, type UploadItem } from "@/lib/upload-tasks"
import { cn } from "@/lib/utils"

export type { UploadItem } from "@/lib/upload-tasks"

/**
 * 上传队列：一次传一个文件，传完一个回调一次（页面据此刷新素材列表）。
 * 首页是先上传、上传时才建项目，所以 add 可以带上刚建好的项目名（这时 batch 参数还没来得及更新）。
 */
export function useUploadQueue(batch: string, onUploaded: () => void, context?: string) {
  const scope = context ?? `batch:${batch}`
  const getSnapshot = useCallback(() => !context && batch ? uploadTasks.getBatchSnapshot(batch) : uploadTasks.getSnapshot(scope), [batch, context, scope])
  const snapshot = useSyncExternalStore(uploadTasks.subscribe, getSnapshot, getSnapshot)
  useEffect(() => {
    const completed = (event: Event) => {
      const detail = (event as CustomEvent<{ scope: string; batch: string }>).detail
      if (detail.scope === scope || (batch && detail.batch === batch)) onUploaded()
    }
    window.addEventListener("jh:upload-complete", completed)
    return () => window.removeEventListener("jh:upload-complete", completed)
  }, [batch, scope, onUploaded])

  const add = useCallback((files: FileList | File[], into?: string) => {
    const list = Array.from(files)
    const good = list.filter(isVideo)
    if (good.length !== list.length) toast.error(`跳过 ${list.length - good.length} 个不是视频的文件`)
    if (!good.length) return
    uploadTasks.add(scope, into || batch || uploadTasks.getSnapshot(scope).batch || "", good)
    toast(`开始上传 ${good.length} 个视频`, { description: `共 ${fmtSize(good.reduce((sum, file) => sum + file.size, 0))}` })
  }, [batch, scope])
  const cancel = useCallback((key: string) => uploadTasks.cancel(key), [])
  const clearDone = useCallback(() => !context && batch ? uploadTasks.clearBatchDone(batch) : uploadTasks.clearDone(scope), [batch, context, scope])
  const reset = useCallback(() => uploadTasks.reset(scope), [scope])
  const busy = snapshot.items.some((item) => item.status === "queued" || item.status === "uploading")
  return { items: snapshot.items, batch: snapshot.batch || batch || null, add, cancel, clearDone, reset, busy }
}

export function useAllUploads() { return useSyncExternalStore(uploadTasks.subscribe, uploadTasks.getAll, uploadTasks.getAll) }

/** 拖拽 / 点击上传区域 */
export function DropZone({ onFiles, big, batch }: { onFiles: (f: FileList) => void; big?: boolean; batch: string }) {
  const [over, setOver] = useState(false)
  const ref = useRef<HTMLInputElement>(null)
  return (
    <>
      <button
        onClick={() => ref.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); onFiles(e.dataTransfer.files) }}
        className={cn("group grid w-full place-items-center rounded-2xl border-2 border-dashed bg-card/60 text-center transition",
          big ? "py-16" : "py-7", over ? "scale-[1.01] border-primary bg-primary/5" : "hover:border-primary/50 hover:bg-primary/[0.03]")}
      >
        <div>
          <motion.div animate={over ? { y: -4, scale: 1.1 } : { y: 0, scale: 1 }} className="mx-auto mb-2 grid size-12 place-items-center rounded-full bg-primary/12 text-gold-ink">
            <UploadCloud className="size-6" />
          </motion.div>
          <div className="font-semibold">{over ? `松开，上传到「${batch}」` : "拖入视频素材，或点击选择"}</div>
          <div className="mt-1 text-xs text-muted-foreground">支持 .mov / .mp4 / .m4v，可以一次选多个；手机原片（4K 竖拍）直接传即可</div>
        </div>
      </button>
      <input ref={ref} type="file" multiple accept={VIDEO_ACCEPT} className="hidden" onChange={(e) => { if (e.target.files?.length) onFiles(e.target.files); e.target.value = "" }} />
    </>
  )
}

export function UploadList({ items, onCancel, onClear, maxVisibleItems }: {
  items: UploadItem[]
  onCancel: (k: string) => void
  onClear: () => void
  maxVisibleItems?: number
}) {
  if (!items.length) return null
  const done = items.filter((x) => x.status === "done").length
  return (
    <div className="soft-shadow mt-3 rounded-xl border bg-card">
      <div className="flex items-center justify-between border-b px-4 py-2.5 text-sm">
        <b>上传队列</b>
        <span className="text-xs text-muted-foreground">{done}/{items.length} 完成 {done > 0 && <button className="ml-2 text-gold-ink hover:underline" onClick={onClear}>清除已完成</button>}</span>
      </div>
      <div className="scrollbar-thin max-h-64 overflow-y-auto"
        style={maxVisibleItems ? { maxHeight: `${maxVisibleItems * 3}rem` } : undefined}>
        <AnimatePresence initial={false}>
          {items.map((it) => {
            const pct = it.file.size ? (it.loaded / it.file.size) * 100 : 0
            return (
              <motion.div key={it.key} layout initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, height: 0 }}
                className={cn("grid grid-cols-[20px_1fr_auto] items-center gap-3 border-b border-border/60 px-4 py-2 last:border-0", maxVisibleItems && "h-12")}>
                {it.status === "done" ? <Check className="size-4 text-ok" /> : it.status === "error" ? <CircleAlert className="size-4 text-destructive" />
                  : it.status === "uploading" ? <Loader2 className="size-4 animate-spin text-gold-ink" /> : <FileVideo className="size-4 text-muted-foreground" />}
                <div className="min-w-0">
                  <div className="flex justify-between gap-2 text-[13px]">
                    <span className="truncate">{it.file.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular">
                      {it.status === "error" ? <span className="text-destructive">{it.error}</span>
                        : it.status === "done" ? fmtSize(it.file.size)
                        : it.status === "queued" ? `排队 · ${fmtSize(it.file.size)}`
                        : `${pct.toFixed(0)}% · ${fmtSize(it.loaded)}/${fmtSize(it.file.size)}${it.speed ? ` · ${fmtSize(it.speed)}/s` : ""}`}
                    </span>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-muted">
                    <motion.div className={cn("h-full", it.status === "done" ? "bg-ok" : it.status === "error" ? "bg-destructive" : "bg-primary")}
                      initial={false} animate={{ width: `${it.status === "done" ? 100 : pct}%` }} transition={{ duration: 0.3 }} />
                  </div>
                </div>
                {(it.status === "queued" || it.status === "uploading") ? (
                  <Button size="icon-xs" variant="ghost" title="取消" onClick={() => onCancel(it.key)}><X /></Button>
                ) : <span className="size-6" />}
              </motion.div>
            )
          })}
        </AnimatePresence>
      </div>
    </div>
  )
}
