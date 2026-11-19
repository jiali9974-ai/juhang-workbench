// 成片画廊：展示所有项目的成片，勾选后批量导出或删除。
import { useEffect, useState } from "react"
import { Check, Download, Film, Loader2, Play, Plus, Trash2, X } from "lucide-react"
import { Dialog } from "radix-ui"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { api, urls, type OutputVideo } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"
import { PAGE_CONTAINER, PAGE_TITLE } from "@/lib/layout"

const keyOf = (video: OutputVideo) => JSON.stringify([video.batch, video.id])

export function GenPage() {
  const { version, active } = useJobs()
  const generating = active.some((job) => job.kind === "auto" || job.kind === "render")
  const [videos, setVideos] = useState<OutputVideo[] | null>(null)
  const [selected, setSelected] = useSessionState<Set<string>>("gallery.selected", () => new Set())
  const [selectedProject, setSelectedProject] = useSessionState<string | null>("gallery.project", null)
  const [preview, setPreview] = useState<OutputVideo | null>(null)
  const [exporting, setExporting] = useSessionState("gallery.exporting", false)
  const [deleting, setDeleting] = useSessionState<string | null>("gallery.deleting", null)

  useEffect(() => {
    let alive = true
    const load = () => api.outputs().then((list) => {
      if (alive) setVideos(list)
    }).catch((e) => {
      if (alive) {
        setVideos((previous) => previous ?? [])
        toast.error("加载成片失败", { description: String(e).replace(/^Error: /, "") })
      }
    })
    load()
    const timer = window.setInterval(load, generating ? 1500 : 5000)
    const visible = () => { if (document.visibilityState === "visible") void load() }
    window.addEventListener("jh:refresh", load)
    window.addEventListener("focus", load)
    document.addEventListener("visibilitychange", visible)
    return () => {
      alive = false
      window.clearInterval(timer)
      window.removeEventListener("jh:refresh", load)
      window.removeEventListener("focus", load)
      document.removeEventListener("visibilitychange", visible)
    }
  }, [version, generating])

  const list = videos ?? []
  const projects = new Map<string, OutputVideo[]>()
  for (const video of list) {
    const group = projects.get(video.batch)
    if (group) group.push(video)
    else projects.set(video.batch, [video])
  }
  const project = selectedProject !== null && projects.has(selectedProject) ? selectedProject : null
  const visible = project === null ? list : projects.get(project) ?? []
  const groups = [...projects].filter(([batch]) => project === null || batch === project)
  const chosen = visible.filter((video) => selected.has(keyOf(video)))
  const allSelected = visible.length > 0 && chosen.length === visible.length
  const busy = exporting || deleting !== null

  function toggle(video: OutputVideo) {
    if (busy) return
    setSelected((previous) => {
      const next = new Set(previous)
      const key = keyOf(video)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  async function exportVideos() {
    if (!chosen.length || busy) return
    setExporting(true)
    try {
      const { url } = await api.exportOutputs(chosen.map(({ batch, id }) => ({ batch, id })))
      const link = document.createElement("a")
      link.href = url
      link.download = "成片.zip"
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (e) {
      toast.error("导出失败", { description: String(e).replace(/^Error: /, "") })
    } finally {
      setExporting(false)
    }
  }

  async function deleteVideos(targets: OutputVideo[]) {
    if (!targets.length || busy) return
    let removed = 0
    const errors: string[] = []
    setDeleting(keyOf(targets[0]))
    try {
      for (const video of targets) {
        const key = keyOf(video)
        setDeleting(key)
        try {
          await api.deleteOutput(video.batch, video.id)
          removed++
          setVideos((previous) => previous?.filter((item) => keyOf(item) !== key) ?? [])
          setSelected((previous) => {
            const next = new Set(previous)
            next.delete(key)
            return next
          })
          setPreview((previous) => previous && keyOf(previous) === key ? null : previous)
        } catch (e) {
          errors.push(`${video.title}：${String(e).replace(/^Error: /, "")}`)
        }
      }
      if (removed) {
        window.dispatchEvent(new Event("jh:refresh"))
        toast.success(`已删除 ${removed} 条成片`)
      }
      if (errors.length) toast.error("删除失败", { description: errors.join("；") })
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className={PAGE_CONTAINER}>
      <div className="mb-8 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h1 className={PAGE_TITLE}>成片</h1>
          <Button variant="outline" size="icon-lg" className="rounded-full" aria-label="上传素材" title="上传素材" onClick={() => go({ page: "home" })}><Plus /></Button>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            项目
            <select aria-label="按项目筛选成片" disabled={busy} value={project === null ? "all" : JSON.stringify(project)}
              onChange={(event) => {
                setSelectedProject(event.target.value === "all" ? null : JSON.parse(event.target.value))
                setSelected(new Set())
              }}
              className="h-10 max-w-52 rounded-full border bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
              <option value="all">全部项目（{list.length}）</option>
              {[...projects].map(([batch, files]) => <option key={batch} value={JSON.stringify(batch)}>{batch || "未分类成片"}（{files.length}）</option>)}
            </select>
          </label>
          {chosen.length > 0 && <span className="text-sm text-muted-foreground" role="status">已选 {chosen.length} 条</span>}
          <Button variant="outline" className="h-10 rounded-full px-5 aria-pressed:bg-muted disabled:bg-muted" aria-pressed={allSelected}
            disabled={!list.length || busy} onClick={() => setSelected(allSelected ? new Set() : new Set(visible.map(keyOf)))}>{allSelected ? "取消全选" : "全选"}</Button>
          <Button className="h-10 min-w-26 rounded-full px-5 disabled:bg-muted" disabled={!chosen.length || busy} aria-busy={exporting} onClick={exportVideos}>
            {exporting ? "导出中…" : "一键导出"}
          </Button>
          <Button className="h-10 rounded-full px-5 disabled:bg-muted" disabled={!chosen.length || busy} aria-busy={deleting !== null} onClick={() => deleteVideos(chosen)}>
            {deleting !== null ? "删除中…" : "删除"}
          </Button>
        </div>
      </div>

      {videos === null ? (
        <div className="grid min-h-[60svh] place-items-center"><Loader2 aria-label="正在加载成片" className="size-6 animate-spin text-muted-foreground" /></div>
      ) : !list.length ? (
        <div className="grid min-h-[60svh] place-items-center text-sm text-muted-foreground">暂无成片</div>
      ) : (
        <div className="space-y-10">
          {groups.map(([batch, files]) => (
            <section key={batch} aria-label={`项目成片：${batch || "未分类成片"}`}>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b pb-3">
                <div className="flex min-w-0 items-baseline gap-3">
                  <h2 className="truncate text-xl font-semibold" title={batch || "未分类成片"}>{batch || "未分类成片"}</h2>
                  <span className="shrink-0 text-sm text-muted-foreground">{files.length} 条成片</span>
                </div>
                <div className="flex items-center gap-2">
                  {batch && <Button size="sm" variant="ghost" onClick={() => go({ page: "batch", batch, tab: "scripts" })}>查看素材项目</Button>}
                  <Button size="sm" variant="outline" className="rounded-full" disabled={busy}
                    aria-label={`全选项目 ${batch || "未分类成片"} 的成片`} aria-pressed={files.every((video) => selected.has(keyOf(video)))}
                    onClick={() => setSelected((previous) => {
                      const next = new Set(previous)
                      const all = files.every((video) => next.has(keyOf(video)))
                      files.forEach((video) => { if (all) next.delete(keyOf(video)); else next.add(keyOf(video)) })
                      return next
                    })}>{files.every((video) => selected.has(keyOf(video))) ? "取消项目全选" : "全选此项目"}</Button>
                </div>
              </div>
              <div role="group" aria-label={`${batch || "未分类成片"}的成片`} className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
                {files.map((video) => {
                  const checked = selected.has(keyOf(video))
                  return (
                    <article key={keyOf(video)} className={cn("group relative overflow-hidden rounded-2xl bg-muted transition-shadow", checked && "ring-2 ring-foreground ring-offset-4 ring-offset-background")}>
                      <div className="relative">
                      <button role="checkbox" aria-checked={checked} aria-label={`选择成片：${video.title}（${video.batch}）`} disabled={busy} onClick={() => toggle(video)}
                        className="relative block aspect-9/16 w-full cursor-pointer overflow-hidden rounded-2xl outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-foreground">
                        <Film aria-hidden="true" className="absolute top-1/2 left-1/2 size-8 -translate-1/2 text-muted-foreground/30" />
                        <img src={`${urls.outputThumb(video.batch, video.id)}&v=${video.updated}`} alt="" loading="lazy"
                          onError={(e) => { e.currentTarget.hidden = true }} className="relative size-full object-cover transition-transform duration-300 group-hover:scale-[1.02]" />
                        <span aria-hidden="true" className={cn("absolute top-3 left-3 grid size-6 place-items-center rounded-full border shadow-sm transition-opacity", checked ? "border-foreground bg-foreground text-background" : "border-white/80 bg-black/20 text-transparent opacity-0 group-hover:opacity-100 group-has-[:focus-visible]:opacity-100")}><Check className="size-4" /></span>
                      </button>
                      <div data-video-actions className="pointer-events-none absolute right-3 bottom-3 flex gap-2 opacity-0 transition-opacity duration-150 group-hover:pointer-events-auto group-hover:opacity-100 group-has-[:focus-visible]:pointer-events-auto group-has-[:focus-visible]:opacity-100">
                        <Button variant="secondary" size="icon" className="rounded-full shadow-sm" aria-label={`预览成片：${video.title}`} title="播放" onClick={() => setPreview(video)}><Play className="size-4" /></Button>
                        <Button variant="secondary" size="icon" asChild className="rounded-full shadow-sm">
                          <a href={urls.output(video.batch, video.id)} download={`${video.id}.mp4`} aria-label={`下载成片：${video.title}`} title="下载"><Download className="size-4" /></a>
                        </Button>
                        <Button variant="secondary" size="icon" className="rounded-full shadow-sm hover:text-destructive" aria-label={`删除成片：${video.title}`} title="删除" disabled={busy} aria-busy={deleting === keyOf(video)} onClick={() => deleteVideos([video])}>
                          {deleting === keyOf(video) ? <Loader2 className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
                        </Button>
                      </div>
                      </div>
                      <div className="truncate px-3 py-3 text-sm font-medium" title={video.title}>{video.title}</div>
                      {video.cover_note && <p className="px-3 pb-3 text-xs leading-relaxed text-amber-700" role="note">{video.cover_note}</p>}
                    </article>
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      )}

      <Dialog.Root open={preview !== null} onOpenChange={(open) => { if (!open) setPreview(null) }}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm" />
          <Dialog.Content aria-describedby={undefined} className="fixed top-1/2 left-1/2 z-50 w-[min(440px,calc(100vw-48px))] -translate-x-1/2 -translate-y-1/2 outline-none">
            <Dialog.Title className="sr-only">{preview?.title}</Dialog.Title>
            {preview && <video key={keyOf(preview)} src={urls.output(preview.batch, preview.id)} poster={`${urls.outputThumb(preview.batch, preview.id)}&v=${preview.updated}`} controls autoPlay playsInline className="max-h-[85svh] w-full rounded-2xl bg-black" />}
            <Dialog.Close asChild><Button size="icon" variant="secondary" className="absolute -top-4 -right-4 rounded-full" aria-label="关闭预览"><X /></Button></Dialog.Close>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  )
}
