import { useCallback, useEffect, useState } from "react"
import { ArrowRight, Check, Clapperboard, Download, Image as ImageIcon, Loader2, Music, RefreshCw, Rocket, Save, ScanEye, Sparkles, Type, Wand2 } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { Phone } from "@/components/bits"
import { DeleteProject, ProjectMissing } from "@/components/delete-project"
import { ease, Stagger, StaggerItem } from "@/components/motion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { useJobs } from "@/hooks/use-jobs"
import { tvcApi, tvcFile, type CloudStatus, type TvcItem, type TvcPlan, type TvcProject } from "@/lib/tvc"
import { cn } from "@/lib/utils"
import { CloudBadge } from "@/pages/tvc-home"
import { PresenterProject } from "@/pages/tvc-presenter"

const ROLE: Record<string, string> = { hook: "开场", feature: "卖点", hero: "定版" }
const REF: Record<string, string> = { A: "A 空棚贴字", B: "B 3D 空间功能词", C: "C 环形折叠字" }

function ItemBadge({ it, busy }: { it?: TvcItem; busy: boolean }) {
  if (busy) return <Badge variant="outline" className="border-primary/40 text-gold-ink"><Loader2 className="animate-spin" />生成中</Badge>
  if (!it || it.status === "pending") return <Badge variant="outline" className="text-muted-foreground">待生成</Badge>
  if (it.status === "stale") return <Badge variant="outline" className="border-warn/50 bg-warn/10 text-warn">需重做</Badge>
  return <Badge variant="outline" className="border-ok/40 bg-ok/10 text-ok"><Check />完成</Badge>
}

export function TvcProjectPage({ id }: { id: string }) {
  const { watch, active, version } = useJobs()
  const [p, setP] = useState<TvcProject | null>(null)
  const [plan, setPlan] = useState<TvcPlan | null>(null)
  const [dirty, setDirty] = useState(false)
  const [cloud, setCloud] = useState<CloudStatus | null>(null)
  const [missing, setMissing] = useState(false)

  const load = useCallback(async () => {
    const proj = await tvcApi.get(id)
    setP(proj)
    setPlan((cur) => (dirty && cur ? cur : proj.plan ? structuredClone(proj.plan) : null))
  }, [id, dirty])

  useEffect(() => {
    setMissing(false)
  }, [id])
  useEffect(() => {
    load().catch(async (e) => {
      // 项目不存在（或刚被删掉）就显示提示，不再一直转圈
      const list = await tvcApi.list().catch(() => null)
      if (list && !list.some((x) => x.id === id)) return setMissing(true)
      toast.error("加载失败", { description: String(e) })
    })
  }, [load, version, id])
  // 有任务在跑时每 4 秒刷新一次，生成好一张就显示一张
  const running = active.some((j) => j.kind === "tvc")
  useEffect(() => {
    if (!running) return
    const t = setInterval(() => load().catch(() => {}), 4000)
    return () => clearInterval(t)
  }, [running, load])
  useEffect(() => {
    tvcApi.cloud().then(setCloud).catch(() => setCloud({ connected: false }))
  }, [running])

  if (missing) return <ProjectMissing kind="tvc" name={id} />
  if (!p) {
    return <div className="mx-auto max-w-[1300px] space-y-3 px-8 pt-8"><Skeleton className="h-9 w-72" /><Skeleton className="h-24" /><Skeleton className="h-80" /></div>
  }
  if (p.style === "presenter") return <PresenterProject p={p} cloud={cloud} reload={load} />

  const kfDone = p.keyframes.length > 0 && p.keyframes.every((k) => k.status === "done")
  const segDone = p.segments.length > 0 && p.segments.every((s) => s.status === "done")
  const currentJob = active.find((j) => j.kind === "tvc")
  const busyKf = (k: number) => !!currentJob && (currentJob.message.includes(`关键帧 ${k}/`) || currentJob.title === `重画关键帧 ${k}`)
  const busySeg = (s: number) => !!currentJob && (currentJob.message.includes(`视频段 ${s}/`) || currentJob.message.includes(`第 ${s} 段`) || currentJob.title === `重做视频段 ${s}`)

  async function act(fn: () => Promise<{ id: string }>, msg: string, done?: string) {
    if (dirty) await savePlan(true)
    const j = await fn()
    toast(msg)
    watch(j as never, () => { if (done) toast.success(done); load() })
  }
  async function savePlan(quiet = false) {
    if (!plan) return
    const proj = await tvcApi.savePlan(id, plan)
    setP(proj)
    setDirty(false)
    if (!quiet) toast.success("提示词已保存", { description: "改过的关键帧和视频段已标为需重做" })
  }
  const editKf = (i: number, v: string) => { setPlan((x) => { if (!x) return x; const y = structuredClone(x); y.keyframes[i].image_prompt = v; return y }); setDirty(true) }
  const editSeg = (i: number, v: string) => { setPlan((x) => { if (!x) return x; const y = structuredClone(x); y.segments[i].video_prompt = v; return y }); setDirty(true) }

  const steps = [
    { t: "识别产品", done: !!p.caption, icon: ScanEye },
    { t: "写方案", done: !!p.plan, icon: Sparkles },
    { t: "出分镜", done: kfDone, icon: ImageIcon },
    { t: "出视频段", done: segDone, icon: Clapperboard },
    { t: "合成成片", done: !!p.final, icon: Rocket },
  ]

  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 pt-6 pb-24 md:px-8">
      {/* 标题 */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs tracking-[0.25em] text-gold-ink">PRODUCT TVC · {p.id}</div>
          <h1 className="mt-1 text-2xl font-bold tracking-wide">{plan?.title || p.brief.product}</h1>
          {plan?.concept && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{plan.concept}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DeleteProject kind="tvc" id={id} name={plan?.title || p.brief.product} size="default" current />
          <CloudBadge s={cloud} />
          {!kfDone ? (
            <Button className="font-bold" disabled={running} aria-busy={running} onClick={() => act(() => tvcApi.run(id, "keyframes"), "开始出分镜", "分镜出好了，请审核")}>
              {running ? <Loader2 className="animate-spin" /> : <Wand2 />}生成分镜
            </Button>
          ) : !p.final ? (
            <Button className="font-bold" disabled={running} aria-busy={running} onClick={() => act(() => tvcApi.run(id, "final"), "开始生成视频段并合成，约 6–8 分钟", "成片出好了")}>
              {running ? <Loader2 className="animate-spin" /> : <Rocket />}确认分镜，生成视频
            </Button>
          ) : (
            <Button variant="outline" asChild><a href={tvcFile(id, p.final)} download={`${plan?.title || id}.mp4`}><Download />下载成片</a></Button>
          )}
        </div>
      </div>

      {/* 步骤 */}
      <div className="mt-5 flex flex-wrap items-center gap-2">
        {steps.map((s, i) => (
          <div key={s.t} className="flex items-center gap-2">
            <span className={cn("flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors",
              s.done ? "border-primary/50 bg-primary/15 text-gold-ink" : "text-muted-foreground")}>
              {s.done ? <Check className="size-3.5" /> : <s.icon className="size-3.5" />}{s.t}
            </span>
            {i < steps.length - 1 && <ArrowRight className="size-3.5 text-muted-foreground/50" />}
          </div>
        ))}
        {currentJob && <span className="ml-2 text-xs text-gold-ink"><Loader2 className="mr-1 inline size-3 animate-spin" />{currentJob.message}</span>}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[260px_1fr]">
        {/* 左：产品与方案 */}
        <div className="grid content-start gap-4 sm:grid-cols-2 lg:grid-cols-1">
          <div className="soft-shadow overflow-hidden rounded-xl border bg-card">
            <img src={tvcFile(id, p.product_file)} className="aspect-square max-h-64 w-full bg-muted object-contain lg:max-h-none" />
            <div className="space-y-1 p-3 text-sm">
              <div className="font-semibold">{p.brief.product}</div>
              {p.brief.brand && <div className="text-xs text-muted-foreground">品牌：{p.brief.brand}</div>}
              {p.brief.selling_points && <div className="text-xs text-muted-foreground">卖点：{p.brief.selling_points}</div>}
            </div>
          </div>
          {p.caption && (
            <details className="soft-shadow rounded-xl border bg-card p-3 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-medium text-foreground"><ScanEye className="mr-1 inline size-3.5" />AI 识别结果</summary>
              <div className="mt-2 whitespace-pre-wrap leading-relaxed">{p.caption}</div>
            </details>
          )}
          {plan && (
            <div className="soft-shadow space-y-2.5 rounded-xl border bg-card p-3 text-xs">
              <div className="flex items-center justify-between"><b className="text-sm">创意方案</b>
                <Button size="xs" variant="ghost" disabled={running} onClick={() => act(() => tvcApi.replan(id), "重新出方案", "新方案出好了")}><RefreshCw />重出</Button>
              </div>
              <div><span className="text-muted-foreground">文字动效：</span><b>{REF[plan.typography_ref] ?? plan.typography_ref}</b><div className="mt-0.5 text-muted-foreground">{plan.typography_reason}</div></div>
              <div className="flex flex-wrap gap-1"><Type className="size-3.5 text-muted-foreground" />{plan.texts.map((t) => <span key={t} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{t}</span>)}</div>
              <div><Music className="mr-1 inline size-3.5 text-muted-foreground" />背景音乐方向：{plan.bgm}</div>
              <div className="text-muted-foreground">产品锚定：{plan.product_anchor}</div>
            </div>
          )}
        </div>

        {/* 右：分镜、视频段、成片 */}
        <div className="grid content-start gap-6">
          {!plan && (
            <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
              {running ? <><Loader2 className="mx-auto mb-2 size-6 animate-spin text-gold-ink" />正在识别产品、写方案…</> : "点右上角「生成分镜」开始"}
            </div>
          )}

          {plan && (
            <section>
              <div className="mb-3 flex items-center gap-2">
                <h2 className="font-semibold">分镜关键帧</h2><span className="text-xs text-muted-foreground">Qwen-Image 2.1 · 每张都参考产品原图 · 第 k 段视频 = 关键帧 k → k+1</span>
                {dirty && <Button size="sm" variant="outline" className="ml-auto border-warn/50 text-warn" onClick={() => savePlan()}><Save />保存提示词修改</Button>}
              </div>
              <Stagger className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                {plan.keyframes.map((k, i) => {
                  const it = p.keyframes[i]
                  return (
                    <StaggerItem key={k.id} className="soft-shadow overflow-hidden rounded-xl border bg-card">
                      <div className="relative aspect-[9/16] bg-muted">
                        <AnimatePresence mode="wait">
                          {it?.file ? (
                            <motion.img key={it.file} src={tvcFile(id, it.file)} initial={{ opacity: 0, scale: 1.03 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.4, ease }}
                              className={cn("size-full object-cover", it.status === "stale" && "opacity-50")} />
                          ) : (
                            <motion.div key="empty" className="grid size-full place-items-center text-muted-foreground">
                              {busyKf(k.id) ? <Loader2 className="size-6 animate-spin text-gold-ink" /> : <ImageIcon className="size-6" />}
                            </motion.div>
                          )}
                        </AnimatePresence>
                        <span className="absolute top-2 left-2 rounded-md bg-black/55 px-1.5 text-xs text-white">{k.id} · {ROLE[k.role] ?? k.role}</span>
                      </div>
                      <div className="space-y-2 p-2.5">
                        <div className="flex items-center justify-between gap-1"><span className="truncate text-xs text-muted-foreground">{k.shot}</span><ItemBadge it={it} busy={busyKf(k.id)} /></div>
                        <div className="flex flex-wrap gap-1">{k.on_screen_text.map((t) => <span key={t} className="rounded bg-muted px-1 font-mono text-[10px]">{t}</span>)}</div>
                        <Textarea value={k.image_prompt} onChange={(e) => editKf(i, e.target.value)} rows={4} className="min-h-0 resize-y text-xs leading-relaxed" />
                        <Button size="sm" variant="outline" className="w-full" disabled={running} onClick={() => act(() => tvcApi.keyframe(id, k.id), `重画关键帧 ${k.id}`, `关键帧 ${k.id} 重画好了`)}>
                          <RefreshCw />{it?.file ? "重画这张" : "生成这张"}
                        </Button>
                      </div>
                    </StaggerItem>
                  )
                })}
              </Stagger>
            </section>
          )}

          {plan && (kfDone || p.segments.some((s) => s.file)) && (
            <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }}>
              <div className="mb-3 flex items-center gap-2"><h2 className="font-semibold">视频段</h2><span className="text-xs text-muted-foreground">MiniMax H3 · fl2va 首尾帧 · 24fps · 自带音效</span></div>
              <div className="grid gap-3 md:grid-cols-3">
                {plan.segments.map((s, i) => {
                  const it = p.segments[i]
                  return (
                    <div key={s.id} className="soft-shadow overflow-hidden rounded-xl border bg-card">
                      <div className="relative aspect-[9/16] bg-muted">
                        {it?.file ? (
                          <video key={it.file} src={tvcFile(id, it.file)} controls playsInline preload="metadata" className={cn("size-full bg-black object-contain", it.status === "stale" && "opacity-50")} />
                        ) : (
                          <div className="grid size-full place-items-center text-muted-foreground">{busySeg(s.id) ? <Loader2 className="size-6 animate-spin text-gold-ink" /> : <Clapperboard className="size-6" />}</div>
                        )}
                      </div>
                      <div className="space-y-2 p-2.5">
                        <div className="flex items-center justify-between"><span className="text-xs text-muted-foreground">第 {s.id} 段 · 关键帧 {s.from} → {s.to} · {s.seconds} 秒</span><ItemBadge it={it} busy={busySeg(s.id)} /></div>
                        <Textarea value={s.video_prompt} onChange={(e) => editSeg(i, e.target.value)} rows={5} className="min-h-0 resize-y font-mono text-[11px] leading-relaxed" />
                        <Button size="sm" variant="outline" className="w-full" disabled={running || !kfDone} onClick={() => act(() => tvcApi.segment(id, s.id), `重做第 ${s.id} 段，约 2–3 分钟`, `第 ${s.id} 段好了`)}>
                          <RefreshCw />{it?.file ? "重做这段" : "生成这段"}
                        </Button>
                      </div>
                    </div>
                  )
                })}
              </div>
              {segDone && !p.final && (
                <Button className="mt-3" variant="outline" disabled={running} onClick={() => act(() => tvcApi.compose(id), "合成成片", "成片好了")}><Rocket />合成成片</Button>
              )}
            </motion.section>
          )}

          {p.final && (
            <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }} className="grid items-start gap-4 md:grid-cols-[340px_1fr]">
              <Phone><video key={p.final} src={tvcFile(id, p.final)} controls playsInline className="size-full bg-black object-contain" /></Phone>
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">成片</h2>
                <p className="text-sm text-muted-foreground">1080×1920 · 24fps · {p.segments.length} 段拼接。音效来自 H3，背景音乐按方向「{plan?.bgm}」后期再铺。</p>
                <div className="flex gap-2">
                  <Button asChild className="font-bold"><a href={tvcFile(id, p.final)} download={`${plan?.title || id}.mp4`}><Download />下载 MP4</a></Button>
                  <Button variant="outline" disabled={running} onClick={() => act(() => tvcApi.compose(id), "重新合成", "重新合成好了")}><RefreshCw />重新合成</Button>
                </div>
              </div>
            </motion.section>
          )}
        </div>
      </div>
    </div>
  )
}
