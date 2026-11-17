import { useEffect, useState } from "react"
import {
  ArrowRight, Check, Clapperboard, Download, Hand, Image as ImageIcon, Loader2, Mic, MapPin, Music, RefreshCw, Rocket, Save,
  ScanEye, Sparkles, UserRound, Wand2,
} from "lucide-react"
import { motion } from "motion/react"
import { toast } from "sonner"

import { Phone } from "@/components/bits"
import { DeleteProject } from "@/components/delete-project"
import { ease, Stagger, StaggerItem } from "@/components/motion"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useJobs } from "@/hooks/use-jobs"
import type { Job } from "@/lib/api"
import { tvcApi, tvcFile, type CloudStatus, type PresenterPlan, type TvcItem, type TvcProject, type TvcShot } from "@/lib/tvc"
import { cn } from "@/lib/utils"
import { CloudBadge } from "@/pages/tvc-home"

const ROLE: Record<string, string> = { hook: "开场", dial: "表盘", bezel: "表圈", bracelet: "表带", wrist: "上手", detail: "细节", cta: "收尾" }

function ItemBadge({ it, busy, label }: { it?: TvcItem; busy: boolean; label: string }) {
  if (busy) return <Badge variant="outline" className="border-primary/40 text-gold-ink"><Loader2 className="animate-spin" />{label}生成中</Badge>
  if (!it || it.status === "pending") return <Badge variant="outline" className="text-muted-foreground">{label}待生成</Badge>
  if (it.status === "stale") return <Badge variant="outline" className="border-warn/50 bg-warn/10 text-warn">{label}需重做</Badge>
  return <Badge variant="outline" className="border-ok/40 bg-ok/10 text-ok"><Check />{label}</Badge>
}

/** 口播带货项目页：每个镜头一张卡片（分镜、镜头视频、粤语文案和配音） */
export function PresenterProject({ p, cloud, reload }: { p: TvcProject; cloud: CloudStatus | null; reload: () => Promise<void> }) {
  const { watch, active } = useJobs()
  const id = p.id
  const toPlan = (x: TvcProject) => (x.plan ? structuredClone(x.plan as unknown as PresenterPlan) : null)
  const [plan, setPlan] = useState<PresenterPlan | null>(() => toPlan(p))
  const [dirty, setDirty] = useState(false)
  const [openPrompt, setOpenPrompt] = useState<number | null>(null)

  useEffect(() => {
    if (!dirty) setPlan(toPlan(p))
  }, [p, dirty])

  const running = active.some((j) => j.kind === "tvc")
  const currentJob = active.find((j) => j.kind === "tvc")
  const kfDone = p.keyframes.length > 0 && p.keyframes.every((k) => k.status === "done")
  const segDone = p.segments.length > 0 && p.segments.every((s) => s.status === "done")
  const voiceDone = (p.voice ?? []).length > 0 && (p.voice ?? []).every(Boolean)
  const busyKf = (k: number) => !!currentJob && (currentJob.message.includes(`关键帧 ${k}/`) || currentJob.title === `重画关键帧 ${k}`)
  const busySeg = (s: number) => !!currentJob && (currentJob.message.includes(`镜头视频 ${s}/`) || currentJob.message.includes(`镜头 ${s} 生成中`) || currentJob.title === `重做视频段 ${s}`)
  const total = (p.voice ?? []).reduce((a, v) => a + (v ? v.dur + 0.25 : 0), 0)
  const linesChanged = (pl: PresenterPlan) => pl.shots.some((s, i) => (s.lines || []).join("|") !== ((p.plan as unknown as PresenterPlan | null)?.shots[i]?.lines || []).join("|"))

  async function save(quiet = false) {
    if (!plan) return
    const changed = linesChanged(plan)
    await tvcApi.savePlan(id, plan)
    setDirty(false)
    if (!quiet) toast.success("修改已保存", { description: changed ? "文案改了，正在重新配音" : "改过提示词的镜头已标为需重做" })
    if (changed) {
      const j = await tvcApi.voice(id)
      watch(j, () => { toast.success("配音更新好了"); reload() })
    } else {
      await reload()
    }
  }
  async function act(fn: () => Promise<Job>, msg: string, done?: string) {
    if (dirty) await save(true)
    const j = await fn()
    toast(msg)
    watch(j, () => { if (done) toast.success(done); reload() })
  }
  const edit = (i: number, patch: Partial<TvcShot>) => {
    setPlan((x) => { if (!x) return x; const y = structuredClone(x); Object.assign(y.shots[i], patch); return y })
    setDirty(true)
  }

  const steps = [
    { t: "识别产品", done: !!p.caption, icon: ScanEye },
    { t: "写口播", done: !!p.plan, icon: Sparkles },
    { t: "粤语配音", done: voiceDone, icon: Mic },
    { t: "出分镜", done: kfDone, icon: ImageIcon },
    { t: "出镜头视频", done: segDone, icon: Clapperboard },
    { t: "合成成片", done: !!p.final, icon: Rocket },
  ]

  return (
    <div className="mx-auto w-full max-w-[1400px] px-6 pt-6 pb-24 md:px-8">
      {/* 标题 */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-xs tracking-[0.25em] text-gold-ink">口播带货 · {p.id}</div>
          <h1 className="mt-1 text-2xl font-bold tracking-wide">{plan?.title || p.brief.product}</h1>
          {plan?.concept && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{plan.concept}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DeleteProject kind="tvc" id={id} name={plan?.title || p.brief.product} size="default" current />
          <CloudBadge s={cloud} />
          {dirty && <Button variant="outline" className="border-warn/50 text-warn" onClick={() => save()}><Save />保存修改</Button>}
          {!kfDone ? (
            <Button className="font-bold" disabled={running} aria-busy={running} onClick={() => act(() => tvcApi.run(id, "keyframes"), "开始出分镜", "分镜出好了，请审核")}>
              {running ? <Loader2 className="animate-spin" /> : <Wand2 />}生成分镜
            </Button>
          ) : !p.final ? (
            <Button className="font-bold" disabled={running} aria-busy={running} onClick={() => act(() => tvcApi.run(id, "final"), `开始生成 ${p.segments.length} 个镜头的视频并合成，约 10–15 分钟`, "成片出好了")}>
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
        {/* 左：产品、主播、方案 */}
        <div className="grid content-start gap-4 sm:grid-cols-2 lg:grid-cols-1">
          <div className="soft-shadow overflow-hidden rounded-xl border bg-card">
            <img src={tvcFile(id, p.product_file)} className="aspect-square max-h-64 w-full bg-muted object-contain lg:max-h-none" />
            <div className="space-y-1 p-3 text-sm">
              <div className="font-semibold">{p.brief.product}</div>
              {p.brief.brand && <div className="text-xs text-muted-foreground">品牌：{p.brief.brand}</div>}
              {p.brief.selling_points && <div className="text-xs text-muted-foreground">卖点：{p.brief.selling_points}</div>}
            </div>
          </div>
          {p.presenter_file && (
            <div className="soft-shadow flex gap-3 rounded-xl border bg-card p-3 text-xs">
              <img src={tvcFile(id, p.presenter_file)} className="aspect-[9/16] w-16 rounded-md bg-muted object-cover" />
              <div className="space-y-1">
                <b className="text-sm">虚拟主播</b>
                <p className="text-muted-foreground">主播镜头都参考这张照片，长相和服装保持一致。换主播在「产品图生视频」首页。</p>
              </div>
            </div>
          )}
          {plan && <div className="soft-shadow space-y-2.5 rounded-xl border bg-card p-3 text-xs">
            <div className="flex items-center justify-between"><b className="text-sm">方案</b>
              <Button size="xs" variant="ghost" disabled={running} onClick={() => act(() => tvcApi.replan(id), "重新写口播和镜头", "新方案出好了")}><RefreshCw />重出</Button>
            </div>
            <div><MapPin className="mr-1 inline size-3.5 text-muted-foreground" />场景：{plan.scene}</div>
            <div><Music className="mr-1 inline size-3.5 text-muted-foreground" />背景音乐方向：{plan.bgm}</div>
            {total > 0 && <div><Mic className="mr-1 inline size-3.5 text-muted-foreground" />配音合计 {total.toFixed(1)} 秒 · {plan.shots.length} 个镜头</div>}
          </div>}
          {p.caption && (
            <details className="soft-shadow rounded-xl border bg-card p-3 text-xs text-muted-foreground">
              <summary className="cursor-pointer font-medium text-foreground"><ScanEye className="mr-1 inline size-3.5" />AI 识别结果</summary>
              <div className="mt-2 whitespace-pre-wrap leading-relaxed">{p.caption}</div>
            </details>
          )}
        </div>

        {/* 右：镜头列表 + 成片 */}
        <div className="grid content-start gap-6">
          {p.final && (
            <motion.section initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease }} className="grid items-start gap-4 md:grid-cols-[320px_1fr]">
              <Phone><video key={p.final} src={tvcFile(id, p.final)} controls playsInline className="size-full bg-black object-contain" /></Phone>
              <div className="space-y-3">
                <h2 className="text-lg font-semibold">成片</h2>
                <p className="text-sm text-muted-foreground">1440×2560 · 粤语配音 · 字幕、左上角「先鉴定后入手 / 只做正品」、底部声明，和素材剪辑出的成片同一套样式。{total > 0 && ` 约 ${total.toFixed(0)} 秒。`}</p>
                <div className="flex gap-2">
                  <Button asChild className="font-bold"><a href={tvcFile(id, p.final)} download={`${plan?.title || id}.mp4`}><Download />下载 MP4</a></Button>
                  <Button variant="outline" disabled={running} onClick={() => act(() => tvcApi.compose(id), "重新合成", "重新合成好了")}><RefreshCw />重新合成</Button>
                </div>
              </div>
            </motion.section>
          )}

          {!plan && (
            <div className="rounded-xl border border-dashed p-10 text-center text-sm text-muted-foreground">
              {running ? <><Loader2 className="mx-auto mb-2 size-6 animate-spin text-gold-ink" />正在识别产品、写口播…</> : "点右上角「生成分镜」开始"}
            </div>
          )}

          {plan && <section>
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <h2 className="font-semibold">镜头</h2>
              <span className="text-xs text-muted-foreground">每个镜头 = 1 张分镜（Qwen-Image 2.1）+ H3 往后生成的视频，时长跟着配音走；文案改完点「保存修改」会自动重新配音</span>
            </div>
            <Stagger className="grid gap-3">
              {plan.shots.map((s, i) => {
                const kf = p.keyframes[i]
                const seg = p.segments[i]
                const v = p.voice?.[i]
                const isPresenter = s.type === "presenter"
                return (
                  <StaggerItem key={s.id} className="soft-shadow grid gap-3 rounded-xl border bg-card p-3 md:grid-cols-[150px_150px_1fr]">
                    {/* 分镜 */}
                    <div className="relative aspect-[9/16] overflow-hidden rounded-lg bg-muted">
                      {kf?.file ? (
                        <img key={kf.file} src={tvcFile(id, kf.file)} className={cn("size-full object-cover", kf.status === "stale" && "opacity-50")} />
                      ) : (
                        <div className="grid size-full place-items-center text-muted-foreground">{busyKf(s.id) ? <Loader2 className="size-6 animate-spin text-gold-ink" /> : <ImageIcon className="size-6" />}</div>
                      )}
                      <span className="absolute top-1.5 left-1.5 rounded bg-black/55 px-1.5 text-[11px] text-white">分镜 {s.id}</span>
                    </div>
                    {/* 镜头视频 */}
                    <div className="relative aspect-[9/16] overflow-hidden rounded-lg bg-muted">
                      {seg?.file ? (
                        <video key={seg.file} src={tvcFile(id, seg.file)} controls playsInline muted preload="metadata" className={cn("size-full bg-black object-cover", seg.status === "stale" && "opacity-50")} />
                      ) : (
                        <div className="grid size-full place-items-center text-muted-foreground">{busySeg(s.id) ? <Loader2 className="size-6 animate-spin text-gold-ink" /> : <Clapperboard className="size-6" />}</div>
                      )}
                      <span className="absolute top-1.5 left-1.5 rounded bg-black/55 px-1.5 text-[11px] text-white">视频{seg?.seconds ? ` ${seg.seconds}s` : ""}</span>
                    </div>
                    {/* 文案、配音、提示词 */}
                    <div className="grid min-w-0 content-start gap-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className={cn("flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium", isPresenter ? "bg-primary/15 text-gold-ink" : "bg-muted text-foreground/80")}>
                          {isPresenter ? <UserRound className="size-3.5" /> : <Hand className="size-3.5" />}{isPresenter ? "主播出镜" : "手持特写"}
                        </span>
                        <span className="text-xs text-muted-foreground">{ROLE[s.role] ?? s.role} · {s.shot}</span>
                        <span className="ml-auto flex gap-1"><ItemBadge it={kf} busy={busyKf(s.id)} label="分镜" /><ItemBadge it={seg} busy={busySeg(s.id)} label="视频" /></span>
                      </div>
                      <Textarea
                        value={s.lines.join("\n")}
                        onChange={(e) => edit(i, { lines: e.target.value.split("\n") })}
                        rows={Math.max(2, s.lines.length)}
                        className="min-h-0 resize-y text-[15px] font-medium leading-relaxed"
                        placeholder="粤语口播，一行一句（同时也是字幕）"
                      />
                      <div className="flex flex-wrap items-center gap-2">
                        {v ? <audio key={v.file} src={tvcFile(id, v.file)} controls preload="none" className="h-8 max-w-[260px]" /> : <span className="text-xs text-muted-foreground"><Mic className="mr-1 inline size-3.5" />还没配音</span>}
                        {v && <span className="text-xs text-muted-foreground tabular">{v.dur.toFixed(1)} 秒</span>}
                        <span className="ml-auto flex gap-1.5">
                          <Button size="sm" variant="ghost" onClick={() => setOpenPrompt(openPrompt === i ? null : i)}>{openPrompt === i ? "收起提示词" : "提示词"}</Button>
                          <Button size="sm" variant="outline" disabled={running} onClick={() => act(() => tvcApi.keyframe(id, s.id), `重画分镜 ${s.id}`, `分镜 ${s.id} 重画好了`)}>
                            <RefreshCw />{kf?.file ? "重画分镜" : "画分镜"}
                          </Button>
                          <Button size="sm" variant="outline" disabled={running || !kf?.file} onClick={() => act(() => tvcApi.segment(id, s.id), `生成镜头 ${s.id} 的视频，约 2 分钟`, `镜头 ${s.id} 好了`)}>
                            <Clapperboard />{seg?.file ? "重做视频" : "生成视频"}
                          </Button>
                        </span>
                      </div>
                      {openPrompt === i && (
                        <div className="grid gap-2">
                          <label className="grid gap-1 text-xs text-muted-foreground">分镜提示词（中文，&lt;image1&gt; = 产品图{isPresenter ? "，<image2> = 主播照片" : ""}）
                            <Textarea value={s.image_prompt} onChange={(e) => edit(i, { image_prompt: e.target.value })} rows={4} className="min-h-0 resize-y text-xs leading-relaxed text-foreground" />
                          </label>
                          <label className="grid gap-1 text-xs text-muted-foreground">视频提示词（英文，MiniMax H3）
                            <Textarea value={s.video_prompt} onChange={(e) => edit(i, { video_prompt: e.target.value })} rows={6} className="min-h-0 resize-y font-mono text-[11px] leading-relaxed text-foreground" />
                          </label>
                        </div>
                      )}
                    </div>
                  </StaggerItem>
                )
              })}
            </Stagger>
            {segDone && !p.final && (
              <Button className="mt-3" variant="outline" disabled={running} onClick={() => act(() => tvcApi.compose(id), "合成成片", "成片好了")}><Rocket />合成成片</Button>
            )}
          </section>}
        </div>
      </div>
    </div>
  )
}
