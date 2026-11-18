// 首页：一个上传框。拖入视频或整个文件夹 → 传完点「开始生成」→ 进入生成页。
import { useCallback, useRef, useState } from "react"
import { Check, CircleAlert, FileVideo, FolderUp, Loader2, RefreshCw, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { ease } from "@/components/motion"
import { useUploadQueue } from "@/components/upload-queue"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { followTask, getRoute, go } from "@/hooks/use-route"
import { api, type Job } from "@/lib/api"
import { setCurrent, todayName } from "@/lib/current"
import { filesFromDrop, fmtSize, folderOf, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"
import { uploadTasks } from "@/lib/upload-tasks"

const msg = (e: unknown) => String(e).replace(/^Error: /, "")
const homeCreation: { promise: Promise<string> | null; name: string | null } = { promise: null, name: null }

export function StartPage() {
  const { watch } = useJobs()
  const [clips, setClips] = useState(0)               // 项目里已经有的视频数
  const [over, setOver] = useState(false)
  const [starting, setStarting] = useSessionState("home.starting", false)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const folderRef = useRef<HTMLInputElement | null>(null)


  const refresh = useCallback(() => {
    window.dispatchEvent(new Event("jh:refresh"))
    api.batches().then((list) => {
      const b = list.find((x) => x.batch === (homeCreation.name ?? uploadTasks.getSnapshot("home").batch))
      if (b) setClips(b.clips)
    }).catch(() => {})
  }, [])
  const queue = useUploadQueue("", refresh, "home")
  const batch = queue.batch

  /** 第一次加素材时才建项目：只拖了一个文件夹就用文件夹名，否则用今天的日期；重名自动加 _2、_3 */
  async function createProject(hint: string | null): Promise<{ batch: string; job: Job | null }> {
    const base = (hint || todayName()).trim()
    for (let i = 1; i <= 50; i++) {
      const name = i === 1 ? base : `${base}_${i}`
      try {
        const r = await api.createBatch(name)
        homeCreation.name = r.batch
        return r
      } catch (e) {
        if (!msg(e).includes("已经有叫")) throw e
      }
    }
    throw new Error("同名项目太多了，换个文件夹名再试")
  }
  function ensureProject(hint: string | null): Promise<string> {
    if (!homeCreation.promise) {
      homeCreation.promise = createProject(hint).then((r) => r.batch)
      homeCreation.promise.catch(() => { homeCreation.promise = null })
    }
    return homeCreation.promise
  }

  async function addFiles(files: File[], folder: string | null) {
    if (!files.some(isVideo)) {
      return toast.error("没有找到视频", { description: "支持 .mov / .mp4 / .m4v，可以直接拖整个文件夹" })
    }
    try {
      const b = await ensureProject(folder)
      queue.add(files, b)
    } catch (e) {
      toast.error("新建项目失败", { description: msg(e) })
    }
  }

  const done = queue.items.filter((x) => x.status === "done").length
  const total = Math.max(clips, done)
  const ready = !!batch && !queue.busy && total > 0

  async function start() {
    if (!batch) return
    const source = getRoute()
    setStarting(true)
    try {
      const j = await api.auto(batch)
      watch(j, (job) => toast.success(`「${batch}」生成完成，共 ${(job.result as string[]).length} 条成片`))
      setCurrent(batch)
      queue.reset()
      homeCreation.promise = null
      homeCreation.name = null
      followTask(source, batch, j.id)
    } catch (e) {
      toast.error("没法开始", { description: msg(e) })
    } finally {
      setStarting(false)
    }
  }

  const bytes = queue.items.reduce((a, x) => a + x.file.size, 0)
  const loaded = queue.items.reduce((a, x) => a + (x.status === "done" ? x.file.size : x.loaded), 0)

  return (
    <div className="flex min-h-svh flex-col bg-background pt-17">
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col px-6 pt-10 pb-24 md:pt-12">
        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="mt-auto text-center text-4xl font-bold tracking-tight md:text-5xl"
        >
          上传素材
        </motion.h1>

        {/* 上传框 */}
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.15, ease }}
          role="button"
          tabIndex={0}
          aria-label="上传视频素材"
          onClick={() => fileRef.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), fileRef.current?.click())}
          onDragOver={(e) => { e.preventDefault(); setOver(true) }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setOver(false)
            filesFromDrop(e.dataTransfer).then(({ files, folder }) => addFiles(files, folder))
          }}
          className={cn(
            "mt-10 flex min-h-72 cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed px-6 py-12 text-center transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 md:min-h-88",
            over ? "scale-[1.01] border-foreground bg-muted/70" : "border-border bg-muted/25 hover:border-foreground/30 hover:bg-muted/50",
          )}
        >
          <div className="text-lg font-semibold">{over ? "松开开始上传" : "拖到这里上传"}</div>
          <div className="mt-5 flex flex-wrap justify-center gap-2" onClick={(e) => e.stopPropagation()}>
            <Button variant="outline" className="rounded-full bg-background" onClick={() => fileRef.current?.click()}>
              <FileVideo />选择视频
            </Button>
            <Button variant="outline" className="rounded-full bg-background" onClick={() => folderRef.current?.click()}>
              <FolderUp />选择文件夹
            </Button>
          </div>
        </motion.div>
        <input
          ref={fileRef}
          type="file"
          multiple
          accept={VIDEO_ACCEPT}
          className="hidden"
          onChange={(e) => { const f = Array.from(e.target.files ?? []); e.target.value = ""; if (f.length) addFiles(f, null) }}
        />
        <input
          ref={(el) => {
            folderRef.current = el
            el?.setAttribute("webkitdirectory", "")
            el?.setAttribute("directory", "")
          }}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => { const f = Array.from(e.target.files ?? []); e.target.value = ""; if (f.length) addFiles(f, folderOf(f)) }}
        />

        {/* 上传进度 */}
        <AnimatePresence initial={false}>
          {queue.items.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.3, ease }}
              className="overflow-hidden"
            >
              <div className="mt-5 rounded-2xl border bg-background">
                <div className="flex items-center justify-between gap-3 px-4 pt-3 text-sm">
                  <span className="font-medium">
                    {queue.busy ? `上传中 ${done}/${queue.items.length}` : `已上传 ${done} 个视频`}
                  </span>
                  <span className="text-xs text-muted-foreground tabular">
                    {queue.items.some((item) => item.status === "error") && (
                      <button className="mr-3 text-gold-ink hover:underline" onClick={queue.retryFailed}>重试失败项</button>
                    )}
                    {fmtSize(loaded)} / {fmtSize(bytes)}
                  </span>
                </div>
                <div className="mx-4 mt-2 mb-3 h-1 overflow-hidden rounded-full bg-muted">
                  <motion.div
                    className="h-full rounded-full bg-foreground"
                    initial={false}
                    animate={{ width: `${(bytes ? loaded / bytes : 0) * 100}%` }}
                    transition={{ duration: 0.3 }}
                  />
                </div>
                {queue.items.length > 0 && (
                  <div className="scrollbar-thin max-h-44 overflow-y-auto border-t">
                    {queue.items.map((it) => (
                      <div key={it.key} className="flex items-center gap-3 px-4 py-1.5 text-[13px]">
                        {it.status === "done" ? <Check className="size-3.5 shrink-0 text-ok" />
                          : it.status === "error" ? <CircleAlert className="size-3.5 shrink-0 text-destructive" />
                          : it.status === "uploading" ? <Loader2 className="size-3.5 shrink-0 animate-spin" />
                          : <FileVideo className="size-3.5 shrink-0 text-muted-foreground" />}
                        <span className="min-w-0 flex-1 truncate" title={`${it.file.name} · 项目：${it.batch}`}>{it.file.name}</span>
                        <span title={it.error} className={cn("max-w-[40%] shrink-0 truncate text-xs tabular", it.status === "error" ? "text-destructive" : "text-muted-foreground")}>
                          {it.status === "error" ? it.error
                            : it.status === "uploading" ? `${Math.round((it.loaded / (it.file.size || 1)) * 100)}%`
                            : it.status === "queued" ? "排队" : fmtSize(it.file.size)}
                        </span>
                        {(it.status === "queued" || it.status === "uploading") && (
                          <button title="取消" onClick={() => queue.cancel(it.key)} className="text-muted-foreground hover:text-foreground"><X className="size-3.5" /></button>
                        )}
                        {it.status === "error" && (
                          <Button size="sm" variant="ghost" className="h-6 gap-1 px-1.5" title={`重新上传到「${it.batch}」`} aria-label={`重试上传 ${it.file.name} 到项目 ${it.batch}`} onClick={() => queue.retry(it.key)}><RefreshCw className="size-3" />重试</Button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 工作台 / 开始 */}
        <div className="mt-auto flex shrink-0 flex-col items-center gap-3 pt-12 text-center">
          <div className="flex items-center justify-center gap-3">
            <Button
              variant="outline"
              size="lg"
              onClick={() => go({ page: "gen" })}
              className="h-12 min-w-32 rounded-full px-6 text-base sm:min-w-36"
            >
              工作台
            </Button>
            <Button
              size="lg"
              disabled={!ready || starting}
              aria-busy={starting}
              onClick={start}
              className="h-12 min-w-32 rounded-full px-6 text-base sm:min-w-36"
            >
              {starting ? <Loader2 className="animate-spin" /> : null}开始生成
            </Button>
          </div>
          {batch && (
            <span className="text-xs text-muted-foreground">
              {queue.busy ? "上传完就可以开始"
                : total ? `项目「${batch}」· ${total} 个视频已就绪 · 自动识别 → 出脚本 → 出片`
                : "还没有传成功的视频"}
            </span>
          )}
        </div>
      </main>
    </div>
  )
}
