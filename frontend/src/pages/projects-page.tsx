// 项目页：左边是全部项目（文字），右边是选中项目的成片视频或素材缩略图。
import { useCallback, useEffect, useState } from "react"
import { FolderOpen, Loader2, Settings2, Sparkles, UploadCloud } from "lucide-react"
import { toast } from "sonner"

import { DeleteProject } from "@/components/delete-project"
import { FeaturePanel, MediaImage, MediaMosaic, MediaVideo, type PanelItem } from "@/components/feature-panel"
import { Button } from "@/components/ui/button"
import { ProjectUpload } from "@/components/project-upload"
import { useAllUploads } from "@/components/upload-queue"
import { useSessionState } from "@/hooks/use-session-state"
import { PAGE_CONTAINER, PAGE_TITLE } from "@/lib/layout"
import { useJobs } from "@/hooks/use-jobs"
import { followTask, getRoute, go } from "@/hooks/use-route"
import { api, urls, type Batch } from "@/lib/api"
import { getCurrent, jobOf, setCurrent } from "@/lib/current"
import { minutes } from "@/lib/format"

type Media = { video?: string; poster?: string; image?: string; thumbs?: string[] }
const mediaCache = new Map<string, Media>()

/** 有成片放第一条成片；有脚本放第一句的画面；只有素材放缩略图拼图 */
function ProjectMedia({ b }: { b: Batch }) {
  const key = `${b.batch}|${b.clips}|${b.scripts}|${b.rendered}|${b.outputs}`
  const [m, setM] = useState<Media | undefined>(() => mediaCache.get(key))
  useEffect(() => {
    let alive = true
    const hit = mediaCache.get(key)
    if (hit) {
      setM(hit)
      return
    }
    setM(undefined)
    ;(async () => {
      const scripts = b.scripts ? await api.scripts(b.batch) : []
      const done = scripts.find((s) => s.has_output)
      const first = scripts[0]?.lines[0]
      let r: Media = {}
      if (done) r = { video: urls.output(b.batch, done.id), poster: urls.outputThumb(b.batch, done.id) }
      else if (first) r = { image: urls.thumb(b.batch, first.clip, (first.start + first.end) / 2) }
      else if (b.clips) {
        const clips = await api.clips(b.batch)
        r = { thumbs: clips.slice(0, 9).map((c) => urls.thumb(b.batch, c.clip, Math.min(3, c.duration / 2))) }
      }
      mediaCache.set(key, r)
      if (alive) setM(r)
    })().catch(() => alive && setM({}))
    return () => {
      alive = false
    }
  }, [key, b])

  if (!m) return <div className="grid size-full place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>
  if (m.video) return <MediaVideo src={m.video} poster={m.poster} />
  if (m.image) return <MediaImage src={m.image} alt={b.batch} />
  if (m.thumbs) return <MediaMosaic srcs={m.thumbs} />
  return (
    <div className="grid size-full place-items-center text-center text-sm text-muted-foreground">
      <div className="grid justify-items-center gap-2"><FolderOpen className="size-6" />还没有素材</div>
    </div>
  )
}

export function ProjectsPage() {
  const { active, version, watch } = useJobs()
  const [list, setList] = useState<Batch[] | null>(null)
  const [sel, setSel] = useSessionState<string | null>("projects.selected", getCurrent)
  const [starting, setStarting] = useSessionState<string | null>("projects.starting", null)
  const uploads = useAllUploads()
  const refresh = useCallback(() => { window.dispatchEvent(new Event("jh:refresh")) }, [])

  const load = useCallback(() => {
    api.batches().then(setList).catch((e) => toast.error("加载失败", { description: String(e) }))
  }, [])
  useEffect(load, [load, version])
  useEffect(() => {
    window.addEventListener("jh:refresh", load)
    return () => window.removeEventListener("jh:refresh", load)
  }, [load])

  async function start(project: Batch) {
    if (starting) return
    const source = getRoute()
    setStarting(project.batch)
    try {
      const job = await api.auto(project.batch)
      watch(job, (done) => toast.success(`已生成 ${(done.result as string[]).length} 条成片`))
      setCurrent(project.batch)
      followTask(source, project.batch, job.id)
    } catch (e) {
      toast.error("没法开始生成", { description: String(e).replace(/^Error: /, "") })
    } finally {
      setStarting(null)
    }
  }

  if (!list) return <div className="grid min-h-svh place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>

  const header = (
    <div className="mb-8">
      <h1 className={PAGE_TITLE}>素材</h1>
    </div>
  )

  const items: PanelItem[] = list.map((b) => {
    const busy = active.some((j) => jobOf(j, b.batch))
    const uploading = uploads.some((item) => item.batch === b.batch && (item.status === "queued" || item.status === "uploading"))
    return {
      key: b.batch,
      title: b.batch,
      badge: (
        <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground tabular">
          {(busy || uploading) && <Loader2 className="size-3.5 animate-spin" />}
          {uploading ? "上传中" : busy ? "生成中" : b.scripts ? `${b.rendered}/${b.scripts} 条成片` : `${b.clips} 个视频`}
        </span>
      ),
      detail: (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground tabular">
            {b.clips} 个视频{b.total_seconds ? ` · ${minutes(b.total_seconds)} 分钟` : ""} · 已识别 {b.transcribed}/{b.clips} · {b.scripts} 条脚本 · {b.rendered} 条已出片
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="rounded-full" disabled={busy || uploading || !!starting || !b.clips} aria-busy={busy || starting === b.batch} onClick={() => start(b)}>
              {starting === b.batch ? <Loader2 className="animate-spin" /> : <Sparkles />}开始生成
            </Button>
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => go({ page: "batch", batch: b.batch, tab: b.clips ? "scripts" : "clips" })}>
              <Settings2 />素材与脚本
            </Button>
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => go({ page: "batch", batch: b.batch, tab: "clips" })}>
              <UploadCloud />补传素材
            </Button>
            <DeleteProject kind="batch" id={b.batch} name={b.batch} size="default" className="h-7 rounded-full px-2.5 text-[0.8rem]" />
          </div>
        </div>
      ),
      media: <ProjectMedia b={b} />,
    }
  })

  return (
    <div className={PAGE_CONTAINER}>
      <FeaturePanel
        header={header}
        items={items}
        active={Math.max(0, list.findIndex((project) => project.batch === sel))}
        onActive={(index) => setSel(list[index].batch)}
        empty={<div className="py-10 text-center text-sm text-muted-foreground">还没有项目</div>}
        footer={<ProjectUpload onCreated={(batch) => { setSel(batch); setCurrent(batch); refresh() }} onUploaded={refresh} />}
      />
    </div>
  )
}
