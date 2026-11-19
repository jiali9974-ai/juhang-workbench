import { useCallback, useEffect, useState } from "react"
import { Check, Clapperboard, Download, FileText, Film, Loader2, Mic, Play, Plus, RefreshCw, Rocket, Sparkles, Wand2 } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { LangBar, LangTag, StatusBadge } from "@/components/bits"
import { ClipSources } from "@/components/clip-sources"
import { DeleteProject, ProjectMissing } from "@/components/delete-project"
import { useUploadQueue } from "@/components/upload-queue"
import { CountUp, ease, GrowBar, Stagger, StaggerItem } from "@/components/motion"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useJobs } from "@/hooks/use-jobs"
import { followTask, getRoute, go, type BatchTab } from "@/hooks/use-route"
import { api, urls, type Batch, type Clip, type Script, type Transcript } from "@/lib/api"
import { minutes, mmss, shortClip, tsec } from "@/lib/format"
import { cn } from "@/lib/utils"

interface Data {
  batch: Batch
  stats: Record<string, number>
  scripts: Script[]
  clips: Clip[]
}

export function BatchPage({ batch, tab }: { batch: string; tab: BatchTab }) {
  const { watch, version, active } = useJobs()
  const [data, setData] = useState<Data | null>(null)
  const [missing, setMissing] = useState(false)

  const load = useCallback(async () => {
    const b = (await api.batches()).find((x) => x.batch === batch)
    if (!b) return setMissing(true)   // 项目不存在或刚被删掉
    const [stats, scripts, clips] = await Promise.all([api.stats(batch), api.scripts(batch), api.clips(batch)])
    setMissing(false)
    setData({ batch: b, stats, scripts, clips })
  }, [batch])

  useEffect(() => {
    setData(null)
    setMissing(false)
  }, [batch])
  const refresh = useCallback(() => {
    load().catch(() => {})
    window.dispatchEvent(new Event("jh:refresh"))
  }, [load])
  const queue = useUploadQueue(batch, refresh)
  const addMaterial = () => {
    go({ page: "batch", batch, tab: "clips" })
    setTimeout(() => document.getElementById("clip-sources")?.scrollIntoView({ behavior: "smooth", block: "center" }), 350)
  }
  useEffect(() => {
    load().catch((e) => toast.error("加载失败", { description: String(e) }))
  }, [load, version])

  const running = queue.busy || active.some((j) => j.title.startsWith(batch))

  async function generate() {
    const source = getRoute()
    const j = await api.generate(batch)
    toast("已开始：先识别，再出脚本", { description: "识别完会自动让大模型出脚本，出完停下来等你审核" })
    watch(j, (job) => toast.success(`脚本已生成，共 ${(job.result as string[]).length} 条`, { description: "逐条审核后再出片" }))
    followTask(source, batch, j.id)
  }
  async function transcribe() {
    const source = getRoute()
    const j = await api.transcribe(batch)
    toast("已开始识别")
    watch(j, () => toast.success("识别完成"))
    followTask(source, batch, j.id)
  }
  async function autoRun() {
    const source = getRoute()
    const j = await api.auto(batch)
    toast("一键出片已开始", { description: "识别 → 出脚本 → 全部出片，进度看右下角" })
    watch(j, (job) => toast.success(`一键出片完成，共 ${(job.result as string[]).length} 条成片`))
    followTask(source, batch, j.id)
  }
  async function renderAll() {
    const source = getRoute()
    const list = await api.renderAll(batch)
    toast(`已加入 ${list.length} 条出片任务`)
    list.forEach((j) => watch(j, (job) => toast.success(`${job.title} 完成`)))
    if (list.length) followTask(source, batch, list[0].id)
  }

  if (missing) return <ProjectMissing kind="batch" name={batch} />
  if (!data) return <BatchSkeleton />

  const { batch: b, stats, scripts, clips } = data
  const totalSec = clips.reduce((a, c) => a + c.duration, 0)
  const speech = Object.values(stats).reduce((a, v) => a + v, 0)
  const yue = stats.yue ?? 0
  const zh = stats.zh ?? 0
  const rendered = scripts.filter((s) => s.status === "rendered").length
  const reviewed = scripts.filter((s) => s.status !== "draft").length
  const pending = scripts.length - rendered
  const tDone = b.clips > 0 && b.transcribed >= b.clips

  const steps = [
    { icon: Mic, title: "语音识别", desc: `${b.transcribed}/${b.clips} 条素材`, done: tDone, doing: b.transcribed > 0, p: b.clips ? b.transcribed / b.clips : 0 },
    { icon: Sparkles, title: "出剪辑脚本", desc: scripts.length ? `${scripts.length} 条脚本` : "大模型按参考结构选句", done: scripts.length > 0, doing: false, p: scripts.length ? 1 : 0 },
    { icon: FileText, title: "人工审核", desc: `${reviewed}/${scripts.length} 条已确认`, done: scripts.length > 0 && reviewed === scripts.length, doing: reviewed > 0, p: scripts.length ? reviewed / scripts.length : 0 },
    { icon: Clapperboard, title: "出片", desc: `${rendered} 条成片`, done: scripts.length > 0 && pending === 0, doing: rendered > 0, p: scripts.length ? rendered / scripts.length : 0 },
  ]

  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 pt-6 pb-40 md:px-8">
      {/* 标题 */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <button onClick={() => go({ page: "projects" })} className="text-xs text-muted-foreground transition-colors hover:text-foreground">← 全部项目</button>
          <h1 className="mt-1 text-3xl font-bold tracking-wide">{b.batch}</h1>
          <div className="mt-1 text-sm text-muted-foreground">{b.clips ? `${b.clips} 条素材 · ${minutes(totalSec)} 分钟` : "还没有素材"}{queue.busy && " · 上传中…"}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <DeleteProject kind="batch" id={batch} name={b.batch} current />
          <Button variant="outline" size="lg" onClick={addMaterial}><Plus />添加素材</Button>
          <Button variant="outline" size="lg" onClick={() => go({ page: "beauty", batch })} disabled={!b.clips}><Wand2 />画面编辑</Button>
          <Button variant="outline" size="lg" onClick={() => go({ page: "gen", batch })}><Film />生成预览</Button>
          {b.transcribed < b.clips && (
            <Button variant="ghost" onClick={transcribe} disabled={running}><Mic />只做识别</Button>
          )}
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button variant="outline" size="lg" disabled={running || !b.clips || queue.busy}><Rocket />一键成片</Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>不审核，直接出片？</AlertDialogTitle>
                <AlertDialogDescription>
                  会自动完成：识别全部素材 → 大模型出剪辑脚本 → 全部出片。全部保留素材原声，字幕对应原话。
                  这一批现有的脚本和成片会挪到归档目录。出完的片子仍可以在「剪辑脚本」里逐条修改后重出。
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>取消</AlertDialogCancel>
                <AlertDialogAction onClick={autoRun}>开始一键出片</AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
          {!scripts.length ? (
            <Button size="lg" className="px-4 font-bold" onClick={generate} disabled={running || !b.clips || queue.busy} aria-busy={running && !queue.busy}>
              {running ? <Loader2 className="animate-spin" /> : <Sparkles />}一键识别并出脚本
            </Button>
          ) : pending ? (
            <>
              <RegenerateButton onConfirm={generate} disabled={running} />
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button size="lg" className="px-4 font-bold"><Play />全部出片（{pending} 条）</Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>把 {pending} 条脚本全部出片？</AlertDialogTitle>
                    <AlertDialogDescription>按当前内容直接出片，还没审核过的脚本也会出。建议先逐条审核。</AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>先不出</AlertDialogCancel>
                    <AlertDialogAction onClick={renderAll}>全部出片</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            </>
          ) : (
            <RegenerateButton onConfirm={generate} disabled={running} />
          )}
        </div>
      </div>

      {!b.clips && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, ease }} className="mt-6">
          <ClipSources batch={batch} queue={queue} big onChanged={refresh} />
        </motion.div>
      )}

      {/* 步骤条 */}
      <Stagger className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {steps.map((s, i) => (
          <StaggerItem key={s.title} className="soft-shadow relative overflow-hidden rounded-xl border bg-card px-4 py-3.5">
            <div className="flex items-center gap-2.5">
              <span className={cn(
                "grid size-6 place-items-center rounded-full border text-xs",
                s.done ? "border-primary bg-primary font-bold text-primary-foreground" : s.doing ? "border-primary text-gold-ink" : "text-muted-foreground",
              )}>
                {s.done ? <motion.span initial={{ scale: 0, rotate: -90 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 400, damping: 18, delay: 0.25 + i * 0.08 }}><Check className="size-3.5" /></motion.span> : i + 1}
              </span>
              <span className="font-semibold">{s.title}</span>
              <s.icon className="ml-auto size-4 text-muted-foreground" />
            </div>
            <div className="mt-1.5 pl-[34px] text-xs text-muted-foreground">{s.desc}</div>
            <GrowBar value={s.p} className="absolute bottom-0 left-0 h-[3px] bg-primary" />
          </StaggerItem>
        ))}
      </Stagger>

      {/* 统计 */}
      <Stagger className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-[1.7fr_1fr_1fr_1fr]">
        <StaggerItem className="soft-shadow col-span-2 rounded-xl border bg-card px-4 py-3.5 lg:col-span-1">
          <div className="text-xs text-muted-foreground">素材语种（已识别部分）</div>
          {speech ? (
            <>
              <LangBar yue={yue} zh={zh} other={Math.max(0, speech - yue - zh)} className="mt-3 mb-2.5" />
              <div className="flex flex-wrap gap-4 text-xs text-foreground/80">
                <span className="flex items-center gap-1.5"><i className="size-2 rounded-sm bg-yue" />粤语 {minutes(yue)} 分</span>
                <span className="flex items-center gap-1.5"><i className="size-2 rounded-sm bg-zh" />普通话 {minutes(zh)} 分</span>
                {speech - yue - zh > 5 && <span className="flex items-center gap-1.5"><i className="size-2 rounded-sm bg-foreground/15" />其他 {minutes(speech - yue - zh)} 分</span>}
              </div>
            </>
          ) : <div className="mt-3 text-sm text-muted-foreground">识别后显示粤语和普通话各占多少</div>}
        </StaggerItem>
        <Stat label="人声时长" value={speech / 60} decimals={1} unit="分钟" />
        <Stat label="剪辑脚本" value={scripts.length} unit="条" />
        <Stat label="成片" value={rendered} unit="条" />
      </Stagger>

      {/* 标签页 */}
      <Tabs value={tab} onValueChange={(v) => go({ page: "batch", batch, tab: v as BatchTab })} className="mt-7">
        <TabsList variant="line" className="h-10 w-full justify-start gap-2 rounded-none border-b p-0">
          <TabsTrigger value="scripts" className="flex-none px-3">剪辑脚本<span className="ml-1.5 rounded-full bg-muted px-1.5 text-[11px] tabular">{scripts.length}</span></TabsTrigger>
          <TabsTrigger value="clips" className="flex-none px-3">素材库<span className="ml-1.5 rounded-full bg-muted px-1.5 text-[11px] tabular">{clips.length}</span></TabsTrigger>
        </TabsList>
      </Tabs>
      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={tab}
          className="mt-5"
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.22, ease }}
        >
          {tab === "scripts" ? <ScriptGrid batch={batch} scripts={scripts} /> : (
            <>
              {b.clips > 0 && <div className="mb-5"><ClipSources batch={batch} queue={queue} onChanged={refresh} /></div>}
              <ClipLibrary batch={batch} clips={clips} />
            </>
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

function RegenerateButton({ onConfirm, disabled }: { onConfirm: () => void; disabled?: boolean }) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="lg" disabled={disabled}><RefreshCw />重新出脚本</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>重新让大模型出脚本？</AlertDialogTitle>
          <AlertDialogDescription>会重新生成这一批的全部脚本。现有的脚本和成片会挪到 _old_时间 归档目录，不会删除，但不再显示在这里。</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction onClick={onConfirm}>重新出脚本</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function Stat({ label, value, unit, decimals = 0 }: { label: string; value: number; unit: string; decimals?: number }) {
  return (
    <StaggerItem className="soft-shadow rounded-xl border bg-card px-4 py-3.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 text-2xl font-bold tabular"><CountUp value={value} decimals={decimals} /><span className="ml-1 text-sm font-normal text-muted-foreground">{unit}</span></div>
    </StaggerItem>
  )
}

function ScriptGrid({ batch, scripts }: { batch: string; scripts: Script[] }) {
  const { watch } = useJobs()
  if (!scripts.length) {
    return (
      <Empty className="border border-dashed">
        <EmptyHeader>
          <EmptyMedia variant="icon"><Sparkles /></EmptyMedia>
          <EmptyTitle>还没有剪辑脚本</EmptyTitle>
          <EmptyDescription>点右上角「一键识别并出脚本」，识别完会自动让大模型出脚本，出完停下来等你审核。</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  }
  async function render(id: string) {
    const source = getRoute()
    const j = await api.render(batch, id)
    toast("已加入出片队列")
    watch(j, () => toast.success(`${id} 出片完成`))
    followTask(source, batch, j.id)
  }
  return (
    <Stagger className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-4">
      {scripts.map((s) => {
        const first = s.lines[0]
        const cover = s.has_output ? urls.outputThumb(batch, s.id) : first ? urls.thumb(batch, first.clip, (first.start + first.end) / 2) : ""
        const zh = s.lines.filter((l) => l.src_lang === "zh").length
        return (
          <StaggerItem key={s.id} className="lift group soft-shadow overflow-hidden rounded-xl border bg-card hover:border-primary/40">
            <button
              className="relative block aspect-[3/4] w-full overflow-hidden bg-muted text-left"
              onClick={() => go({ page: "script", batch, id: s.id })}
            >
              <span
                className="absolute inset-0 bg-cover bg-center transition-transform duration-700 ease-out group-hover:scale-[1.06]"
                style={{ backgroundImage: cover ? `url('${cover}')` : undefined }}
              />
              <span className="absolute inset-0 z-[1] grid place-items-center opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                <span className="grid size-12 scale-75 place-items-center rounded-full bg-white/90 text-foreground shadow-lg transition-transform duration-300 group-hover:scale-100">
                  <FileText className="size-5" />
                </span>
              </span>
              <span className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-black/85" />
              <StatusBadge status={s.status} className="absolute top-2.5 left-2.5 border-white/30 bg-white/85 backdrop-blur" />
              {s.has_output && <Film className="absolute top-3 right-3 size-4 text-white/80" />}
              <span className="absolute right-14 bottom-3 left-3 line-clamp-2 text-[15px] leading-snug font-bold text-white drop-shadow">{s.title}</span>
              <span className="absolute right-3 bottom-3 rounded-md bg-black/55 px-1.5 text-xs text-white tabular">{s.duration}s</span>
            </button>
            <div className="p-3">
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <span>{s.lines.length} 句</span>·
                <span>保留原声</span>
                {zh > 0 && <LangTag lang="zh" className="ml-auto" />}
              </div>
              <div className="mt-2.5 flex gap-2">
                <Button size="sm" variant="secondary" className="flex-1" onClick={() => go({ page: "script", batch, id: s.id })}>审核</Button>
                {s.has_output ? (
                  <Button size="sm" variant="outline" className="flex-1" asChild>
                    <a href={urls.output(batch, s.id)} download><Download />下载</a>
                  </Button>
                ) : (
                  <Button size="sm" variant="outline" className="flex-1" onClick={() => render(s.id)}><Play />出片</Button>
                )}
              </div>
            </div>
          </StaggerItem>
        )
      })}
    </Stagger>
  )
}

function ClipLibrary({ batch, clips }: { batch: string; clips: Clip[] }) {
  const [open, setOpen] = useState<Transcript | null>(null)
  async function show(c: Clip) {
    if (!c.transcribed) return toast("这条素材还没识别")
    setOpen(await api.transcript(batch, c.clip))
  }
  return (
    <div className="grid gap-5 xl:grid-cols-[1fr_420px]">
      <Stagger className="grid content-start gap-2.5 sm:grid-cols-2 2xl:grid-cols-3">
        {clips.map((c) => {
          const y = c.lang.yue ?? 0
          const z = c.lang.zh ?? 0
          return (
            <StaggerItem key={c.clip}>
            <button
              onClick={() => show(c)}
              className={cn("lift soft-shadow grid w-full grid-cols-[56px_1fr] gap-3 rounded-xl border bg-card p-2.5 text-left hover:border-primary/40", open?.clip === c.clip && "border-primary/50 bg-primary/5")}
            >
              <img loading="lazy" src={urls.thumb(batch, c.clip, Math.min(3, c.duration / 2))} className="h-[100px] w-14 rounded-md bg-muted object-cover" />
              <div className="min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-semibold">{shortClip(c.clip)}</span>
                  <span className="text-xs text-muted-foreground tabular">{mmss(c.duration)}</span>
                </div>
                {c.transcribed ? (
                  <>
                    <LangBar yue={y} zh={z} className="mt-2 mb-1.5 h-1.5" />
                    <div className="text-[11px] text-muted-foreground">{c.sentences} 句 · 粤 {Math.round(y)}s · 普 {Math.round(z)}s</div>
                    <div className="mt-1 line-clamp-2 text-xs text-muted-foreground/90">{c.preview_text}</div>
                  </>
                ) : <div className="mt-2 text-xs text-muted-foreground">未识别</div>}
              </div>
            </button>
            </StaggerItem>
          )
        })}
      </Stagger>
      <div className="xl:sticky xl:top-4 xl:self-start">
        <AnimatePresence mode="wait">
        {open ? (
          <motion.div
            key={open.clip}
            className="soft-shadow rounded-xl border bg-card"
            initial={{ opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -8 }}
            transition={{ duration: 0.28, ease }}
          >
            <div className="flex items-center justify-between border-b px-4 py-3">
              <b className="text-sm">{shortClip(open.clip)} 识别文字</b>
              <span className="text-xs text-muted-foreground">{open.sentences.length} 句 · {mmss(open.duration)}</span>
            </div>
            <div className="scrollbar-thin max-h-[70vh] overflow-y-auto px-4 py-2">
              {open.sentences.map((s, i) => (
                <motion.div key={i} initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: Math.min(i, 20) * 0.02, duration: 0.25 }} className="grid grid-cols-[86px_24px_1fr] gap-2 border-b border-dashed border-border py-1.5 text-[13px] last:border-0">
                  <span className="text-[11px] text-muted-foreground tabular">{tsec(s.start)}–{tsec(s.end)}</span>
                  <LangTag lang={s.lang} />
                  <span>{s.text}</span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        ) : (
          <motion.div key="empty" exit={{ opacity: 0 }} className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">点左边的素材，查看逐句识别文字</motion.div>
        )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function BatchSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1400px] space-y-4 px-8 pt-8">
      <Skeleton className="h-10 w-48" />
      <div className="grid grid-cols-4 gap-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>
      <div className="grid grid-cols-5 gap-4">{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="aspect-[3/4]" />)}</div>
    </div>
  )
}
