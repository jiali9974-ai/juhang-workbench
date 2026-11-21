// 首页：一个上传框。拖入视频或整个文件夹 → 传完点「开始生成」→ 进入生成页。
import { useCallback, useRef, useState } from "react"
import { FileVideo, FolderUp, Loader2 } from "lucide-react"
import { motion } from "motion/react"
import { toast } from "sonner"

import { ease } from "@/components/motion"
import { useUploadQueue } from "@/components/upload-queue"
import { UploadGroups } from "@/components/upload-groups"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { followTask, getRoute, go } from "@/hooks/use-route"
import { api } from "@/lib/api"
import { jobOf, setCurrent } from "@/lib/current"
import { filesFromDrop, folderOf, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"
import { createUploadProject, groupUploads } from "@/lib/upload-projects"

const msg = (e: unknown) => String(e).replace(/^Error: /, "")

export function StartPage() {
  const { watch, active } = useJobs()
  const [over, setOver] = useState(false)
  const [starting, setStarting] = useSessionState("home.starting", false)
  const [creating, setCreating] = useSessionState("home.creating", 0)
  const [started, setStarted] = useSessionState<string[]>("home.started", [])
  const fileRef = useRef<HTMLInputElement | null>(null)
  const folderRef = useRef<HTMLInputElement | null>(null)
  const refresh = useCallback(() => window.dispatchEvent(new Event("jh:refresh")), [])
  const queue = useUploadQueue("", refresh, "home")
  const groups = [...groupUploads(queue.items)]
  const readyGroups = groups.filter(([batch, items]) => !started.includes(batch)
    && !active.some((job) => jobOf(job, batch))
    && items.some((item) => item.status === "done")
    && items.every((item) => item.status === "done" || item.status === "cancelled"))
  const ready = !queue.busy && !creating && readyGroups.length > 0

  async function addFiles(files: File[], folder: string | null) {
    if (!files.some(isVideo)) return toast.error("没有找到视频", { description: "支持 .mov / .mp4 / .m4v，可以直接拖整个文件夹" })
    setCreating((count) => count + 1)
    try {
      const batch = await createUploadProject(files, folder)
      queue.add(files, batch)
      refresh()
    } catch (error) {
      toast.error("新建项目失败", { description: msg(error) })
    } finally {
      setCreating((count) => count - 1)
    }
  }

  async function start() {
    if (!ready || starting) return
    const source = getRoute()
    setStarting(true)
    try {
      for (const [batch] of readyGroups) {
        try {
          const job = await api.auto(batch)
          watch(job, (done) => toast.success(`「${batch}」生成完成，共 ${(done.result as string[]).length} 条成片`))
          setStarted((previous) => [...previous, batch])
          setCurrent(batch)
          followTask(source, batch, job.id)
        } catch (error) {
          toast.error(`「${batch}」没法开始`, { description: msg(error) })
        }
      }
    } finally {
      setStarting(false)
    }
  }

  return (
    <div className="flex h-svh min-h-[38rem] flex-col bg-background">
      <main className="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col justify-center px-6 py-8 md:py-10">
        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="shrink-0 text-center text-4xl font-bold tracking-tight md:text-5xl"
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
            filesFromDrop(e.dataTransfer).then((groups) => Promise.all(groups.map(({ files, folder }) => addFiles(files, folder))))
              .catch((error) => toast.error("读取素材失败", { description: msg(error) }))
          }}
          className={cn(
            "mt-6 flex min-h-44 shrink-0 cursor-pointer flex-col items-center justify-center rounded-3xl border-2 border-dashed px-6 py-6 text-center transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-foreground/30 md:min-h-52",
            over ? "scale-[1.01] border-foreground bg-muted/70" : "border-border bg-muted/25 hover:border-foreground/30 hover:bg-muted/50",
          )}
        >
          <div className="text-lg font-semibold">{over ? "松开创建新素材项目" : "拖到这里上传"}</div>
          <p className="mt-2 text-sm text-muted-foreground">每个文件夹独立一个项目，再次拖入会创建新项目</p>
          <div className="mt-5 flex flex-wrap justify-center gap-2" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
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

        <UploadGroups items={queue.items} submitted={started} clearable={false} />

        {/* 工作台 / 开始 */}
        <div className="mt-6 flex shrink-0 flex-col items-center gap-3 text-center">
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
              {starting ? <Loader2 className="animate-spin" /> : null}{readyGroups.length > 1 ? `开始生成（${readyGroups.length} 个项目）` : "开始生成"}
            </Button>
          </div>
          {groups.length > 0 && (
            <span className="text-xs text-muted-foreground" role="status">
              {creating ? "正在创建新的素材项目"
                : queue.busy ? `${groups.length} 个素材项目 · 上传完就可以开始`
                : readyGroups.length ? `${readyGroups.length} 个项目已就绪 · 分别识别、生成脚本和出片`
                : "可在素材页查看各项目，或继续拖入新的文件夹"}
            </span>
          )}
        </div>
      </main>
    </div>
  )
}
