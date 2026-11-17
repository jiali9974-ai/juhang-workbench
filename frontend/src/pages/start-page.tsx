// 首页：一个上传框。拖入视频或整个文件夹 → 传完点「开始生成」→ 进入生成页。
import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowRight, Check, CircleAlert, FileVideo, FolderInput, FolderUp, Loader2, UploadCloud, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { ease } from "@/components/motion"
import { useUploadQueue } from "@/components/upload-queue"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { api, type Batch, type Job } from "@/lib/api"
import { setCurrent, todayName } from "@/lib/current"
import { filesFromDrop, fmtSize, folderOf, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { cn } from "@/lib/utils"

const msg = (e: unknown) => String(e).replace(/^Error: /, "")

export function StartPage() {
  const { jobs, watch } = useJobs()
  const [batch, setBatch] = useState<string | null>(null)
  const [clips, setClips] = useState(0)               // 项目里已经有的视频数
  const [projects, setProjects] = useState<Batch[]>([])
  const [over, setOver] = useState(false)
  const [showPath, setShowPath] = useState(false)
  const [path, setPath] = useState("")
  const [importId, setImportId] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  const creating = useRef<Promise<string> | null>(null)
  const creatingName = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement | null>(null)
  const folderRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => { api.batches().then(setProjects).catch(() => {}) }, [])

  const refresh = useCallback(() => {
    window.dispatchEvent(new Event("jh:refresh"))
    api.batches().then((list) => {
      setProjects(list)
      const b = list.find((x) => x.batch === creatingName.current)
      if (b) setClips(b.clips)
    }).catch(() => {})
  }, [])
  const queue = useUploadQueue(batch ?? "", refresh)

  /** 第一次加素材时才建项目：只拖了一个文件夹就用文件夹名，否则用今天的日期；重名自动加 _2、_3 */
  async function createProject(hint: string | null, folder?: string): Promise<{ batch: string; job: Job | null }> {
    const base = (hint || todayName()).trim()
    for (let i = 1; i <= 50; i++) {
      const name = i === 1 ? base : `${base}_${i}`
      try {
        const r = await api.createBatch(name, folder)
        creatingName.current = r.batch
        setBatch(r.batch)
        return r
      } catch (e) {
        if (!msg(e).includes("已经有叫")) throw e
      }
    }
    throw new Error("同名项目太多了，换个文件夹名再试")
  }
  function ensureProject(hint: string | null): Promise<string> {
    if (!creating.current) {
      creating.current = createProject(hint).then((r) => r.batch)
      creating.current.catch(() => { creating.current = null })
    }
    return creating.current
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

  // 本机路径加载：同一块硬盘用硬链接，几十 GB 也是秒加
  async function importPath() {
    const p = path.trim().replace(/^"|"$/g, "")
    if (!p) return toast.error("请填写本机文件夹路径")
    try {
      let job: Job | null
      if (creating.current) {
        job = await api.importFolder(await creating.current, p)
      } else {
        const name = p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || null
        const r = createProject(name, p)
        creating.current = r.then((x) => x.batch)
        job = (await r).job
      }
      if (!job) return
      setImportId(job.id)
      setShowPath(false)
      setPath("")
      watch(job, (j) => {
        const r = j.result as { added: number; linked: number; total: number }
        toast.success(`已加载 ${r.added} 个视频`, { description: r.linked ? `${r.linked} 个用硬链接，没有占用额外硬盘空间` : undefined })
        refresh()
      })
    } catch (e) {
      toast.error("加载失败", { description: msg(e) })
    }
  }

  const importJob = importId ? jobs.find((j) => j.id === importId) : undefined
  const importing = !!importId && (!importJob || importJob.status === "queued" || importJob.status === "running")
  const done = queue.items.filter((x) => x.status === "done").length
  const total = Math.max(clips, done)
  const ready = !!batch && !queue.busy && !importing && total > 0

  async function start() {
    if (!batch) return
    setStarting(true)
    try {
      const j = await api.auto(batch)
      watch(j, (job) => toast.success(`「${batch}」生成完成，共 ${(job.result as string[]).length} 条成片`))
      setCurrent(batch)
      go({ page: "gen", batch })
    } catch (e) {
      toast.error("没法开始", { description: msg(e) })
      setStarting(false)
    }
  }

  const bytes = queue.items.reduce((a, x) => a + x.file.size, 0)
  const loaded = queue.items.reduce((a, x) => a + (x.status === "done" ? x.file.size : x.loaded), 0)

  return (
    <div className="flex min-h-svh flex-col bg-background">
      <header className="flex items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2.5 text-[15px] font-semibold">
          <span className="grid size-7 place-items-center rounded-lg bg-foreground text-[13px] font-bold text-background">巨</span>
          巨航剪辑工作台
        </div>
        {projects.length > 0 && (
          <button onClick={() => go({ page: "projects" })} className="group flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground">
            我的项目<span className="tabular">（{projects.length}）</span>
            <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
          </button>
        )}
      </header>

      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col justify-center px-6 pb-24">
        <motion.h1
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="text-center text-4xl font-bold tracking-tight md:text-5xl"
        >
          上传素材
        </motion.h1>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.1 }}
          className="mt-3 text-center text-muted-foreground"
        >
          拖入视频或整个文件夹，传完点「开始生成」，自动剪成竖屏短视频
        </motion.p>

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
            "mt-10 grid cursor-pointer place-items-center rounded-3xl border-2 border-dashed px-6 py-14 text-center transition-all duration-200 outline-none focus-visible:ring-2 focus-visible:ring-foreground/30",
            over ? "scale-[1.01] border-foreground bg-muted/70" : "border-border bg-muted/25 hover:border-foreground/30 hover:bg-muted/50",
          )}
        >
          <motion.div
            animate={over ? { y: -6, scale: 1.08 } : { y: 0, scale: 1 }}
            className="grid size-14 place-items-center rounded-full bg-background text-foreground shadow-sm ring-1 ring-foreground/10"
          >
            <UploadCloud className="size-6" />
          </motion.div>
          <div className="mt-4 text-lg font-semibold">{over ? "松开开始上传" : "拖到这里上传"}</div>
          <div className="mt-1 text-sm text-muted-foreground">支持 .mov / .mp4 / .m4v，手机原片直接传，文件夹里的子文件夹也会一起传</div>
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
          {(queue.items.length > 0 || importing) && (
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
                    {importing ? (importJob?.message || "正在加载文件夹…") : queue.busy ? `上传中 ${done}/${queue.items.length}` : `已上传 ${done} 个视频`}
                  </span>
                  <span className="text-xs text-muted-foreground tabular">
                    {importing ? `${Math.round((importJob?.progress ?? 0) * 100)}%` : `${fmtSize(loaded)} / ${fmtSize(bytes)}`}
                  </span>
                </div>
                <div className="mx-4 mt-2 mb-3 h-1 overflow-hidden rounded-full bg-muted">
                  <motion.div
                    className="h-full rounded-full bg-foreground"
                    initial={false}
                    animate={{ width: `${(importing ? importJob?.progress ?? 0 : bytes ? loaded / bytes : 0) * 100}%` }}
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
                        <span className="min-w-0 flex-1 truncate">{it.file.name}</span>
                        <span className={cn("shrink-0 text-xs tabular", it.status === "error" ? "text-destructive" : "text-muted-foreground")}>
                          {it.status === "error" ? it.error
                            : it.status === "uploading" ? `${Math.round((it.loaded / (it.file.size || 1)) * 100)}%`
                            : it.status === "queued" ? "排队" : fmtSize(it.file.size)}
                        </span>
                        {(it.status === "queued" || it.status === "uploading") && (
                          <button title="取消" onClick={() => queue.cancel(it.key)} className="text-muted-foreground hover:text-foreground"><X className="size-3.5" /></button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* 开始 */}
        <div className="mt-8 flex flex-col items-center gap-3">
          <Button
            size="lg"
            disabled={!ready || starting}
            onClick={start}
            className="h-12 rounded-full bg-foreground px-9 text-base text-background hover:bg-foreground/85"
          >
            {starting ? <Loader2 className="animate-spin" /> : null}开始生成{!starting && <ArrowRight />}
          </Button>
          <span className="text-xs text-muted-foreground">
            {!batch ? "先上传素材"
              : queue.busy || importing ? "上传完就可以开始"
              : total ? `项目「${batch}」· ${total} 个视频已就绪 · 自动识别 → 出脚本 → 出片`
              : "还没有传成功的视频"}
          </span>
        </div>

        {/* 本机文件夹路径（大素材更快） */}
        <div className="mt-8 text-center">
          {!showPath ? (
            <button onClick={() => setShowPath(true)} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline">
              <FolderInput className="size-3.5" />素材就在这台电脑上？填文件夹路径直接加载，不用上传
            </button>
          ) : (
            <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="flex gap-2">
              <Input
                autoFocus
                value={path}
                onChange={(e) => setPath(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") importPath(); if (e.key === "Escape") setShowPath(false) }}
                placeholder="例如 D:\巨航\素材\素材\9.29"
                className="rounded-full font-mono text-xs"
              />
              <Button variant="outline" className="shrink-0 rounded-full" onClick={importPath}><FolderInput />加载</Button>
            </motion.div>
          )}
        </div>
      </main>
    </div>
  )
}
