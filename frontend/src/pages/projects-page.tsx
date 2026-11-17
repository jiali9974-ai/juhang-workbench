// 项目页：左边是全部项目（文字），右边是选中项目的成片视频或素材缩略图。
import { useCallback, useEffect, useState } from "react"
import { FolderOpen, Loader2, Plus, Settings2, Sparkles } from "lucide-react"
import { toast } from "sonner"

import { DeleteProject } from "@/components/delete-project"
import { FeaturePanel, MediaImage, MediaMosaic, MediaVideo, type PanelItem } from "@/components/feature-panel"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { api, urls, type Batch } from "@/lib/api"
import { getCurrent, jobOf } from "@/lib/current"
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
  const { active, version } = useJobs()
  const [list, setList] = useState<Batch[] | null>(null)
  const [sel, setSel] = useState<number | null>(null)

  const load = useCallback(() => {
    api.batches().then(setList).catch((e) => toast.error("加载失败", { description: String(e) }))
  }, [])
  useEffect(load, [load, version])
  useEffect(() => {
    window.addEventListener("jh:refresh", load)
    return () => window.removeEventListener("jh:refresh", load)
  }, [load])
  // 第一次进来默认选中当前项目
  useEffect(() => {
    if (list && sel === null) setSel(Math.max(0, list.findIndex((b) => b.batch === getCurrent())))
  }, [list, sel])

  if (!list) return <div className="grid min-h-svh place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>

  const header = (
    <div className="mb-8">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">全部项目</span>
        <Button variant="ghost" size="sm" className="rounded-full text-muted-foreground" onClick={() => go({ page: "home" })}><Plus />新项目</Button>
      </div>
      <h1 className="mt-3 text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl">项目</h1>
      <p className="mt-4 text-sm text-muted-foreground">
        {list.length ? `${list.length} 个项目，最近改过的在前面。点一个看成片，或者进去改素材和脚本。` : ""}
      </p>
    </div>
  )

  const items: PanelItem[] = list.map((b) => {
    const busy = active.some((j) => jobOf(j, b.batch))
    return {
      key: b.batch,
      title: b.batch,
      badge: (
        <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground tabular">
          {busy && <Loader2 className="size-3.5 animate-spin" />}
          {busy ? "生成中" : b.scripts ? `${b.rendered}/${b.scripts} 条成片` : `${b.clips} 个视频`}
        </span>
      ),
      detail: (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground tabular">
            {b.clips} 个视频{b.total_seconds ? ` · ${minutes(b.total_seconds)} 分钟` : ""} · 已识别 {b.transcribed}/{b.clips} · {b.scripts} 条脚本 · {b.rendered} 条已出片
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="rounded-full bg-foreground text-background hover:bg-foreground/85" onClick={() => go({ page: "gen", batch: b.batch })}>
              <Sparkles />查看生成
            </Button>
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => go({ page: "batch", batch: b.batch, tab: b.clips ? "scripts" : "clips" })}>
              <Settings2 />素材与脚本
            </Button>
            <DeleteProject kind="batch" id={b.batch} name={b.batch} size="default" className="h-7 rounded-full px-2.5 text-[0.8rem]" />
          </div>
        </div>
      ),
      media: <ProjectMedia b={b} />,
    }
  })

  return (
    <div className="mx-auto max-w-6xl px-6 pt-10 pb-40">
      <FeaturePanel
        header={header}
        items={items}
        active={Math.min(sel ?? 0, Math.max(0, items.length - 1))}
        onActive={setSel}
        empty={
          <div className="rounded-2xl border border-dashed p-10 text-center text-sm text-muted-foreground">
            还没有项目
            <div className="mt-4">
              <Button className="rounded-full bg-foreground text-background hover:bg-foreground/85" onClick={() => go({ page: "home" })}>上传素材</Button>
            </div>
          </div>
        }
      />
    </div>
  )
}
