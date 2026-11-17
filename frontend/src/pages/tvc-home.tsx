import { useEffect, useRef, useState } from "react"
import { Check, Cloud, CloudOff, Film, ImagePlus, Loader2, Mic, Rocket, Sparkles, Type, Upload, UserRound, Wand2 } from "lucide-react"
import { toast } from "sonner"

import { Stagger, StaggerItem } from "@/components/motion"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { presenterFile, tvcApi, tvcFile, type CloudStatus, type Presenter, type TvcStyle, type TvcSummary } from "@/lib/tvc"
import { cn } from "@/lib/utils"

const STAGE: Record<string, string> = {
  created: "待开始", analyzed: "已识别", planned: "方案已出", keyframes: "分镜待审核", done: "已出片",
}

const STYLES: Record<TvcStyle, { name: string; desc: string; icon: typeof Mic; flow: [string, string][]; time: string }> = {
  presenter: {
    name: "口播带货",
    desc: "照参考作品：虚拟主播出镜开场 → 手持特写转表讲卖点 → 主播收尾引导，粤语配音 + 字幕 + 左上角黄字 + 底部声明",
    icon: Mic,
    flow: [["识别产品", "Qwen3-VL 看图"], ["写口播", "大模型按老板语气"], ["粤语配音", "Ming 粤语"], ["出分镜", "Qwen-Image 2.1 × 6"], ["出镜头视频", "H3 × 6 个镜头"], ["合成成片", "字幕角标 · 20–35 秒"]],
    time: "分镜约 2–3 分钟；整条成片约 12–18 分钟",
  },
  typography: {
    name: "贴字广告 TVC",
    desc: "影棚产品广告：3D 空间英文大字围绕产品，首尾帧连续运镜，15 秒，无配音",
    icon: Type,
    flow: [["识别产品", "Qwen3-VL 看图"], ["写方案", "大模型按 TVC 规则"], ["出分镜", "Qwen-Image 2.1 × 4"], ["出视频段", "H3 首尾帧 × 3"], ["合成成片", "1080×1920 · 15 秒"]],
    time: "分镜约 1 分钟；整条成片约 7–9 分钟",
  },
}

export function CloudBadge({ s }: { s: CloudStatus | null }) {
  if (!s) return <span className="text-xs text-muted-foreground"><Loader2 className="mr-1 inline size-3 animate-spin" />连接云端…</span>
  if (!s.connected) return <span className="text-xs text-destructive"><CloudOff className="mr-1 inline size-3.5" />云端未连接{s.error ? `：${s.error}` : ""}</span>
  const free = s.vram_free && s.vram_total ? `${(s.vram_free / 2 ** 30).toFixed(0)}/${(s.vram_total / 2 ** 30).toFixed(0)}GB 空闲` : ""
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ok/30 bg-ok/10 px-2.5 py-0.5 text-xs text-ok">
      <Cloud className="size-3.5" />AutoDL · {(s.gpu || "").replace(/^cuda:\d+\s*/, "").replace(/\s*:.*$/, "")} {free}
      {s.running ? ` · 运行 ${s.running}` : ""}{s.pending ? ` · 排队 ${s.pending}` : ""}
    </span>
  )
}

function readImage(f: File | undefined, cb: (data: string, name: string) => void) {
  if (!f) return
  if (!f.type.startsWith("image/")) return toast.error("请选择图片文件")
  const r = new FileReader()
  r.onload = () => cb(String(r.result), f.name)
  r.readAsDataURL(f)
}

/** 虚拟主播：口播带货里出镜的人，全工作台共用一个 */
function PresenterCard() {
  const { watch, active } = useJobs()
  const [data, setData] = useState<{ presenter: Presenter | null; default_prompt: string } | null>(null)
  const [prompt, setPrompt] = useState("")
  const [editing, setEditing] = useState(false)
  const upRef = useRef<HTMLInputElement>(null)
  const busy = active.some((j) => j.title === "生成虚拟主播")

  const load = () => tvcApi.presenter().then((d) => { setData(d); setPrompt((cur) => cur || d.presenter?.prompt || d.default_prompt) }).catch(() => {})
  useEffect(() => { load() }, [])

  async function generate() {
    try {
      const j = await tvcApi.presenterGenerate(prompt)
      toast("正在生成虚拟主播，约 30 秒")
      watch(j, () => { toast.success("虚拟主播生成好了"); load() })
    } catch (e) {
      toast.error("生成失败", { description: String(e).replace(/^Error: /, "") })
    }
  }
  function upload(f: File | undefined) {
    readImage(f, async (img, name) => {
      try {
        await tvcApi.presenterUpload(img, name)
        toast.success("已换成上传的照片")
        load()
      } catch (e) {
        toast.error("上传失败", { description: String(e).replace(/^Error: /, "") })
      }
    })
  }

  const pr = data?.presenter
  return (
    <div className="soft-shadow grid gap-3 rounded-xl border bg-card p-3 sm:grid-cols-[96px_1fr]">
      <div className="relative aspect-[9/16] w-24 overflow-hidden rounded-lg bg-muted">
        {pr ? <img src={presenterFile(pr.file)} className="size-full object-cover" /> : (
          <div className="grid size-full place-items-center text-muted-foreground">{busy ? <Loader2 className="size-5 animate-spin text-gold-ink" /> : <UserRound className="size-6" />}</div>
        )}
        {busy && pr && <div className="absolute inset-0 grid place-items-center bg-black/40"><Loader2 className="size-5 animate-spin text-white" /></div>}
      </div>
      <div className="grid content-start gap-2 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <b>虚拟主播</b>
          <span className="text-xs text-muted-foreground">{pr ? (pr.source === "uploaded" ? "用的是上传的照片" : "AI 生成") : "还没有，出方案时会按默认描述自动生成一个"}</span>
        </div>
        <p className="text-xs text-muted-foreground">所有口播带货视频都由这位主播出镜，像店里固定的主播。换主播只影响之后新出的方案。</p>
        {editing && <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} className="text-xs leading-relaxed" placeholder="描述主播的长相、年龄、发型、服装、所在场景" />}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={() => (editing ? generate() : setEditing(true))}>
            {busy ? <Loader2 className="animate-spin" /> : <Wand2 />}{editing ? "按描述生成" : pr ? "换一个主播" : "生成主播"}
          </Button>
          {editing && <Button size="sm" variant="ghost" onClick={() => { setPrompt(data?.default_prompt || ""); }}>恢复默认描述</Button>}
          <Button size="sm" variant="ghost" onClick={() => upRef.current?.click()}><Upload />上传照片</Button>
          <input ref={upRef} type="file" accept="image/*" className="hidden" onChange={(e) => { upload(e.target.files?.[0]); e.target.value = "" }} />
        </div>
      </div>
    </div>
  )
}

export function TvcHome() {
  const { watch } = useJobs()
  const [cloud, setCloud] = useState<CloudStatus | null>(null)
  const [list, setList] = useState<TvcSummary[]>([])
  const [img, setImg] = useState<{ data: string; name: string } | null>(null)
  const [style, setStyle] = useState<TvcStyle>(() => {
    try { return (localStorage.getItem("jh.tvc.style") as TvcStyle) || "presenter" } catch { return "presenter" }
  })
  const [form, setForm] = useState({ product: "", brand: "", selling_points: "", notes: "" })
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const S = STYLES[style]

  useEffect(() => {
    tvcApi.cloud().then(setCloud).catch(() => setCloud({ connected: false }))
    tvcApi.list().then(setList).catch(() => {})
  }, [])
  useEffect(() => {
    try { localStorage.setItem("jh.tvc.style", style) } catch { /* 无痕模式忽略 */ }
  }, [style])

  async function start(until: "keyframes" | "final") {
    if (!img) return toast.error("请先上传产品图")
    if (!form.product.trim()) return toast.error("请填写产品名称")
    setBusy(true)
    try {
      const r = await tvcApi.create({ ...form, style, image: img.data, filename: img.name, until })
      toast(until === "keyframes" ? `已开始：识别 → ${style === "presenter" ? "写口播 → 配音" : "出方案"} → 出分镜` : "已开始一键出片", { description: "进度看右下角" })
      if (r.job) watch(r.job, () => toast.success(until === "keyframes" ? "分镜出好了，请审核" : "成片出好了"))
      window.dispatchEvent(new Event("jh:refresh"))
      go({ page: "tvc-project", id: r.project.id })
    } catch (e) {
      toast.error("创建失败", { description: String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-[1300px] px-6 pt-6 pb-24 md:px-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs tracking-[0.25em] text-gold-ink">PRODUCT VIDEO</div>
          <h1 className="mt-1 text-3xl font-bold tracking-wide">产品图生视频</h1>
          <p className="mt-1 text-sm text-muted-foreground">一张产品图 → 大模型写方案 → Qwen-Image 出分镜 → MiniMax H3 出视频 → 竖屏成片</p>
        </div>
        <CloudBadge s={cloud} />
      </div>

      {/* 风格 */}
      <div className="mt-6 grid gap-3 md:grid-cols-2">
        {(Object.keys(STYLES) as TvcStyle[]).map((k) => {
          const it = STYLES[k]
          const on = style === k
          return (
            <button key={k} onClick={() => setStyle(k)}
              className={cn("soft-shadow relative flex gap-3 rounded-xl border bg-card p-4 text-left transition",
                on ? "border-primary ring-2 ring-primary/30" : "hover:border-primary/40")}>
              <span className={cn("grid size-9 shrink-0 place-items-center rounded-lg", on ? "gold-gradient text-primary-foreground" : "bg-muted text-muted-foreground")}><it.icon className="size-4.5" /></span>
              <span className="min-w-0">
                <span className="flex items-center gap-2 font-semibold">{it.name}{k === "presenter" && <span className="rounded-full bg-primary/15 px-1.5 text-[10px] text-gold-ink">照参考作品</span>}</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">{it.desc}</span>
              </span>
              {on && <Check className="absolute top-3 right-3 size-4 text-gold-ink" />}
            </button>
          )
        })}
      </div>

      {/* 流程 */}
      <Stagger key={style} className={cn("mt-4 grid grid-cols-2 gap-2.5", S.flow.length === 6 ? "md:grid-cols-6" : "md:grid-cols-5")}>
        {S.flow.map(([t, d], i) => (
          <StaggerItem key={t} className="soft-shadow rounded-xl border bg-card px-3.5 py-3">
            <div className="flex items-center gap-2 text-sm font-semibold"><span className="grid size-5 place-items-center rounded-full bg-primary/15 text-[11px] text-gold-ink">{i + 1}</span>{t}</div>
            <div className="mt-1 pl-7 text-xs text-muted-foreground">{d}</div>
          </StaggerItem>
        ))}
      </Stagger>

      {/* 新建 */}
      <div className="soft-shadow mt-5 grid gap-5 rounded-2xl border bg-card p-5 md:grid-cols-[300px_1fr]">
        <button
          onClick={() => fileRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); readImage(e.dataTransfer.files[0], (data, name) => setImg({ data, name })) }}
          className={cn("group relative grid aspect-square place-items-center overflow-hidden rounded-xl border-2 border-dashed bg-muted/40 transition",
            drag ? "border-primary bg-primary/5" : "hover:border-primary/50")}
        >
          {img ? (
            <>
              <img src={img.data} className="size-full object-contain" />
              <span className="absolute inset-x-0 bottom-0 bg-black/50 py-1.5 text-xs text-white opacity-0 transition group-hover:opacity-100">点击更换</span>
            </>
          ) : (
            <div className="text-center text-sm text-muted-foreground">
              <ImagePlus className="mx-auto mb-2 size-9 text-gold-ink transition-transform group-hover:scale-110" />
              点击或拖入产品图<div className="mt-1 text-xs">实物图、官方图、电商白底图都可以</div>
            </div>
          )}
        </button>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => readImage(e.target.files?.[0], (data, name) => setImg({ data, name }))} />
        <div className="grid content-start gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">产品名称 <span className="text-xs text-muted-foreground">必填，比自动识别更准</span>
              <Input value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} placeholder="例如：劳力士 GMT-Master II 黑圈 116710LN" />
            </label>
            <label className="grid gap-1.5 text-sm">品牌名 <span className="text-xs text-muted-foreground">{style === "presenter" ? "选填，口播里会提到" : "选填，会作为画面大字"}</span>
              <Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} placeholder={style === "presenter" ? "例如：劳力士" : "例如：ROLEX"} />
            </label>
          </div>
          {style === "presenter" ? (
            <label className="grid gap-1.5 text-sm">卖点和信息 <span className="text-xs text-muted-foreground">选填，只有这里写了的型号、年份、成色、配件、价格，口播里才会说</span>
              <Textarea value={form.selling_points} onChange={(e) => setForm({ ...form, selling_points: e.target.value })} rows={2} placeholder="例如：126334，蓝盘钻刻，白金狗牙圈，近年份大全套，成色好靓" />
            </label>
          ) : (
            <label className="grid gap-1.5 text-sm">核心卖点 <span className="text-xs text-muted-foreground">选填，会变成画面里的 3D 功能词</span>
              <Input value={form.selling_points} onChange={(e) => setForm({ ...form, selling_points: e.target.value })} placeholder="例如：两地时区、黑色陶瓷表圈、蚝式钢" />
            </label>
          )}
          <label className="grid gap-1.5 text-sm">{style === "presenter" ? "场景 / 其他要求" : "风格 / 其他要求"}
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2}
              placeholder={style === "presenter" ? "选填。场景可选：店内柜台 / 户外木桌 / 会客圆桌；也可以写结尾想怎么引导" : "例如：高级感、黑色影棚、节奏快一些"} />
          </label>
          {style === "presenter" && <PresenterCard />}
          <div className="mt-1 flex flex-wrap gap-2">
            <Button size="lg" className="gold-gradient shine font-bold" disabled={busy} onClick={() => start("keyframes")}>
              {busy ? <Loader2 className="animate-spin" /> : <Wand2 />}生成分镜（先审核）
            </Button>
            <Button size="lg" variant="outline" disabled={busy} onClick={() => start("final")}><Rocket />一键直接出片</Button>
            <span className="self-center text-xs text-muted-foreground">{S.time}</span>
          </div>
        </div>
      </div>

      {/* 项目列表 */}
      <h2 className="mt-8 mb-3 flex items-center gap-2 font-semibold"><Film className="size-4 text-gold-ink" />项目</h2>
      {list.length ? (
        <Stagger className="grid grid-cols-[repeat(auto-fill,minmax(180px,1fr))] gap-4">
          {list.map((p) => (
            <StaggerItem key={p.id} className="lift soft-shadow overflow-hidden rounded-xl border bg-card">
              <button className="block w-full text-left" onClick={() => go({ page: "tvc-project", id: p.id })}>
                <div className="relative aspect-[9/16] bg-muted bg-cover bg-center" style={{ backgroundImage: p.cover ? `url('${tvcFile(p.id, p.cover)}')` : undefined }}>
                  {!p.cover && <div className="grid size-full place-items-center text-muted-foreground"><Sparkles className="size-6" /></div>}
                  <span className="absolute top-2 left-2 rounded-md bg-black/55 px-1.5 text-[11px] text-white">{STYLES[p.style ?? "typography"].name}</span>
                </div>
                <div className="p-3">
                  <div className="truncate text-sm font-semibold">{p.title}</div>
                  <div className="mt-0.5 flex items-center justify-between text-xs text-muted-foreground">
                    <span>{STAGE[p.stage] ?? p.stage}</span><span>{new Date(p.created * 1000).toLocaleDateString()}</span>
                  </div>
                </div>
              </button>
            </StaggerItem>
          ))}
        </Stagger>
      ) : <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">还没有项目，上传一张产品图开始</div>}
    </div>
  )
}
