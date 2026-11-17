// 生成页：左边是进度和成片列表（文字），右边是选中那条的视频；还没有成片时右边是素材缩略图。
import { useCallback, useEffect, useState } from "react"
import { Check, CircleAlert, Download, Loader2, PencilLine, Play, Plus, RotateCcw, Settings2, Sparkles } from "lucide-react"
import { motion } from "motion/react"
import { toast } from "sonner"

import { ProjectMissing } from "@/components/delete-project"
import { FeaturePanel, MediaImage, MediaMosaic, MediaVideo, type PanelItem } from "@/components/feature-panel"
import { ease } from "@/components/motion"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { api, urls, type Batch, type Clip, type Job, type Script } from "@/lib/api"
import { jobOf, setCurrent } from "@/lib/current"
import { minutes } from "@/lib/format"
import { cn } from "@/lib/utils"

const msg = (e: unknown) => String(e).replace(/^Error: /, "")
const PIPELINE = ["auto", "generate", "transcribe", "render"]

const STEPS = [
  { title: "语音识别", desc: "逐句识别粤语和普通话，带时间戳" },
  { title: "出剪辑脚本", desc: "大模型按「开头钩子 → 逐只表讲解 → 结尾引导」选句，写粤语字幕" },
  { title: "出片", desc: "1440×2560 · 60fps · 字幕角标 · 美颜调色；有普通话的自动换成粤语配音" },
]

/** 任务进行到哪一步：0 识别、1 出脚本、2 出片 */
function stageOf(j: Job): number {
  if (j.kind === "transcribe") return 0
  if (j.kind === "render") return 2
  if (j.kind === "generate") return /脚本/.test(j.message) ? 1 : 0
  // 一键出片：进度 0–1/3 识别、1/3–2/3 出脚本、2/3–1 出片
  return j.progress < 1 / 3 ? 0 : j.progress < 2 / 3 ? 1 : 2
}

export function GenPage({ batch }: { batch: string }) {
  const { jobs, active, watch, version } = useJobs()
  const [b, setB] = useState<Batch | null>(null)
  const [scripts, setScripts] = useState<Script[] | null>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [missing, setMissing] = useState(false)
  const [sel, setSel] = useState(0)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    setCurrent(batch)
    setB(null)
    setScripts(null)
    setClips([])
    setSel(0)
    setMissing(false)
  }, [batch])

  const job = active.find((j) => jobOf(j, batch) && PIPELINE.includes(j.kind))
  const running = !!job
  const stage = job ? stageOf(job) : -1
  const last = jobs.find((j) => jobOf(j, batch) && j.kind !== "render" && PIPELINE.includes(j.kind))

  const load = useCallback(async () => {
    const found = (await api.batches()).find((x) => x.batch === batch)
    if (!found) return setMissing(true)
    setB(found)
    setScripts(await api.scripts(batch))
  }, [batch])

  useEffect(() => {
    load().catch((e) => toast.error("加载失败", { description: msg(e) }))
    api.clips(batch).then(setClips).catch(() => {})
  }, [load, batch, version])
  // 生成过程中每 3 秒刷新一次：出完一条就能在左边看到
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => load().catch(() => {}), 3000)
    return () => clearInterval(t)
  }, [running, load])
  // 进度走到下一步时，左边自动跟着选中；到出片这步列表换成成片，从第一条开始
  useEffect(() => {
    if (stage >= 0) setSel(stage < 2 ? stage : 0)
  }, [stage])

  async function startAuto() {
    setStarting(true)
    try {
      const j = await api.auto(batch)
      watch(j, (job) => toast.success(`「${batch}」生成完成，共 ${(job.result as string[]).length} 条成片`))
      setSel(0)
    } catch (e) {
      toast.error("没法开始", { description: msg(e) })
    } finally {
      setStarting(false)
    }
  }
  async function render(id: string) {
    try {
      const j = await api.render(batch, id)
      toast("已加入出片队列")
      watch(j, () => toast.success(`${id} 出片完成`))
    } catch (e) {
      toast.error("没法出片", { description: msg(e) })
    }
  }
  async function renderAll() {
    try {
      const list = await api.renderAll(batch)
      toast(`已加入 ${list.length} 条出片任务`)
      list.forEach((j) => watch(j, (job) => toast.success(`${job.title} 完成`)))
    } catch (e) {
      toast.error("没法出片", { description: msg(e) })
    }
  }

  if (missing) return <ProjectMissing kind="batch" name={batch} />
  if (!b || !scripts) {
    return <div className="grid min-h-svh place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>
  }

  // 哪条正在出片、出到多少
  const renderingNow = new Map<string, number>()
  if (job && job.kind === "auto" && stage === 2) {
    const m = job.message.match(/第 (\d+)\/(\d+) 条/)
    if (m) {
      const i = Number(m[1]) - 1
      const n = Number(m[2])
      if (scripts[i]) renderingNow.set(scripts[i].id, Math.max(0, Math.min(1, job.progress * 3 * n - 2 * n - i)))
    }
  }
  for (const j of active) {
    if (j.kind === "render" && jobOf(j, batch)) renderingNow.set(j.title.replace(/ 出片$/, ""), j.status === "running" ? j.progress : -1)
  }

  const rendered = scripts.filter((s) => s.has_output).length
  const pending = scripts.length - rendered
  // 重新生成时旧脚本要等新脚本出来才归档，这之前先显示步骤，不显示旧的
  const showSteps = !scripts.length || (!!job && (job.kind === "auto" || job.kind === "generate") && stage < 2)
  const failed = !running && last?.status === "error"

  const title = running ? "正在生成" : scripts.length && !pending ? "生成完成" : "生成"
  const header = (
    <div className="mb-8">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button onClick={() => go({ page: "projects" })} className="text-xs text-muted-foreground transition-colors hover:text-foreground">
          项目 · <span className="text-foreground/80">{batch}</span>
        </button>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" className="rounded-full text-muted-foreground" onClick={() => go({ page: "batch", batch, tab: "scripts" })}>
            <Settings2 />素材与脚本
          </Button>
          <Button variant="ghost" size="sm" className="rounded-full text-muted-foreground" onClick={() => go({ page: "home" })}>
            <Plus />新项目
          </Button>
        </div>
      </div>
      <motion.h1
        key={title}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease }}
        className="mt-3 text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl"
      >
        {title}
      </motion.h1>

      {/* 进度 / 状态 */}
      {job ? (
        <div className="mt-6 rounded-2xl border p-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            {STEPS.map((s, i) => (
              <span key={s.title} className={cn("flex items-center gap-1.5", i === stage ? "font-medium text-foreground" : i < stage ? "text-foreground/70" : "text-muted-foreground/60")}>
                {i < stage ? <Check className="size-3.5" /> : i === stage ? <Loader2 className="size-3.5 animate-spin" /> : <span className="size-1.5 rounded-full bg-current" />}
                {s.title}
              </span>
            ))}
          </div>
          <div className="mt-3 h-1 overflow-hidden rounded-full bg-muted">
            <motion.div className="h-full rounded-full bg-foreground" initial={false} animate={{ width: `${Math.round(job.progress * 100)}%` }} transition={{ duration: 0.5, ease }} />
          </div>
          <div className="mt-2 flex justify-between gap-3 text-xs text-muted-foreground">
            <span className="truncate">{job.status === "queued" ? "排队中，前面的任务做完就开始" : job.message || "准备中"}</span>
            <span className="tabular">{Math.round(job.progress * 100)}%</span>
          </div>
        </div>
      ) : failed ? (
        <div className="mt-6 flex flex-wrap items-center gap-3 rounded-2xl border border-destructive/30 bg-destructive/5 p-4 text-sm">
          <CircleAlert className="size-4 shrink-0 text-destructive" />
          <span className="min-w-0 flex-1 text-destructive">上次生成出错：{last?.error.split("\n")[0]}</span>
          <Button size="sm" variant="outline" className="rounded-full" disabled={starting} onClick={startAuto}><RotateCcw />重新生成</Button>
        </div>
      ) : !b.clips ? (
        <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          这个项目还没有素材
          <Button size="sm" variant="outline" className="rounded-full" onClick={() => go({ page: "batch", batch, tab: "clips" })}>去添加素材</Button>
        </div>
      ) : !scripts.length ? (
        <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {b.clips} 个视频已就绪{b.total_seconds ? ` · ${minutes(b.total_seconds)} 分钟` : ""}
          <Button size="sm" className="rounded-full bg-foreground text-background hover:bg-foreground/85" disabled={starting} onClick={startAuto}>
            {starting ? <Loader2 className="animate-spin" /> : <Sparkles />}开始生成
          </Button>
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          <span>{rendered}/{scripts.length} 条已出片 · 点一条看成片</span>
          {pending > 0 && (
            <Button size="sm" className="rounded-full bg-foreground text-background hover:bg-foreground/85" onClick={renderAll}><Play />剩下 {pending} 条全部出片</Button>
          )}
        </div>
      )}
    </div>
  )

  if (showSteps) {
    const thumbs = clips.slice(0, 9).map((c) => urls.thumb(batch, c.clip, Math.min(3, c.duration / 2)))
    const items: PanelItem[] = STEPS.map((s, i) => ({
      key: s.title,
      title: s.title,
      badge: stage > i || (i === 0 && !running && b.clips > 0 && b.transcribed >= b.clips)
        ? <Check className="size-4 text-muted-foreground" />
        : stage === i ? <Loader2 className="size-4 animate-spin text-muted-foreground" /> : null,
      detail: (
        <p className="text-sm leading-relaxed text-muted-foreground">
          {s.desc}
          {i === 0 && b.clips > 0 && <span className="mt-1 block text-xs tabular">已识别 {b.transcribed}/{b.clips} 个视频</span>}
        </p>
      ),
      media: null,
    }))
    return (
      <div className="mx-auto max-w-6xl px-6 pt-10 pb-40">
        <FeaturePanel
          header={header}
          items={items}
          active={sel}
          onActive={setSel}
          aside={
            <MediaMosaic srcs={thumbs}>
              {job && (
                <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 to-transparent p-4 pt-16 text-white">
                  <div className="flex items-center gap-2 text-sm font-medium"><Loader2 className="size-4 animate-spin" />{STEPS[Math.max(0, stage)].title}中</div>
                  <div className="mt-1 truncate text-xs text-white/75">{job.message}</div>
                </div>
              )}
              {!thumbs.length && <div className="absolute inset-0 grid place-items-center text-sm text-muted-foreground">素材缩略图</div>}
            </MediaMosaic>
          }
        />
      </div>
    )
  }

  const items: PanelItem[] = scripts.map((s) => {
    const first = s.lines[0]
    const cover = s.has_output ? urls.outputThumb(batch, s.id) : first ? urls.thumb(batch, first.clip, (first.start + first.end) / 2) : ""
    const doing = renderingNow.get(s.id)
    const state = s.has_output ? "done" : doing !== undefined ? (doing >= 0 ? "doing" : "queued") : running ? "queued" : "idle"
    return {
      key: s.id,
      title: s.title,
      badge: (
        <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground tabular">
          {state === "done" ? <><Check className="size-3.5" />已出片</>
            : state === "doing" ? <><Loader2 className="size-3.5 animate-spin" />{Math.round((doing ?? 0) * 100)}%</>
            : state === "queued" ? "排队出片"
            : s.status === "draft" ? "待审核" : "未出片"}
        </span>
      ),
      detail: (
        <div className="space-y-3">
          <div className="text-xs text-muted-foreground tabular">
            {s.duration ?? 0} 秒 · {s.lines.length} 句 · {s.resolved_voice === "tts_all" ? "粤语配音" : "原声"}
          </div>
          <p className="line-clamp-3 text-sm leading-relaxed text-muted-foreground">{s.lines.map((l) => l.subtitle).join("，")}</p>
          <div className="flex flex-wrap gap-2">
            {s.has_output && (
              <Button size="sm" asChild className="rounded-full bg-foreground text-background hover:bg-foreground/85">
                <a href={urls.output(batch, s.id)} download={`${s.id}.mp4`} onClick={(e) => e.stopPropagation()}><Download />下载</a>
              </Button>
            )}
            <Button size="sm" variant="outline" className="rounded-full" onClick={() => go({ page: "script", batch, id: s.id })}><PencilLine />审核修改</Button>
            {state === "idle" && <Button size="sm" variant="outline" className="rounded-full" onClick={() => render(s.id)}><Play />出片</Button>}
          </div>
        </div>
      ),
      media: s.has_output ? (
        <MediaVideo src={urls.output(batch, s.id)} poster={cover} />
      ) : (
        <div className="relative size-full">
          {cover && <MediaImage src={cover} alt={s.title} />}
          <div className="absolute inset-0 grid place-items-center bg-black/35 text-white">
            <div className="grid justify-items-center gap-2 text-sm font-medium">
              {state === "doing" || state === "queued" ? <Loader2 className="size-6 animate-spin" /> : <Play className="size-6" />}
              {state === "doing" ? `出片中 ${Math.round((doing ?? 0) * 100)}%` : state === "queued" ? "排队出片" : "还没出片"}
            </div>
          </div>
        </div>
      ),
    }
  })

  return (
    <div className="mx-auto max-w-6xl px-6 pt-10 pb-40">
      <FeaturePanel header={header} items={items} active={sel} onActive={setSel} />
    </div>
  )
}
