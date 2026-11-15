import { useEffect, useRef, useState } from "react"
import { Cloud, CloudOff, Film, ImagePlus, Loader2, Rocket, Sparkles, Wand2 } from "lucide-react"
import { toast } from "sonner"

import { Stagger, StaggerItem } from "@/components/motion"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useJobs } from "@/hooks/use-jobs"
import { go } from "@/hooks/use-route"
import { tvcApi, tvcFile, type CloudStatus, type TvcSummary } from "@/lib/tvc"
import { cn } from "@/lib/utils"

const STAGE: Record<string, string> = {
  created: "待开始", analyzed: "已识别", planned: "方案已出", keyframes: "分镜待审核", done: "已出片",
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

export function TvcHome() {
  const { watch } = useJobs()
  const [cloud, setCloud] = useState<CloudStatus | null>(null)
  const [list, setList] = useState<TvcSummary[]>([])
  const [img, setImg] = useState<{ data: string; name: string } | null>(null)
  const [form, setForm] = useState({ product: "", brand: "", selling_points: "", notes: "" })
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    tvcApi.cloud().then(setCloud).catch(() => setCloud({ connected: false }))
    tvcApi.list().then(setList).catch(() => {})
  }, [])

  function pick(f: File | undefined) {
    if (!f) return
    if (!f.type.startsWith("image/")) return toast.error("请选择图片文件")
    const r = new FileReader()
    r.onload = () => setImg({ data: String(r.result), name: f.name })
    r.readAsDataURL(f)
  }

  async function start(until: "keyframes" | "final") {
    if (!img) return toast.error("请先上传产品图")
    if (!form.product.trim()) return toast.error("请填写产品名称")
    setBusy(true)
    try {
      const r = await tvcApi.create({ ...form, image: img.data, filename: img.name, until })
      toast(until === "keyframes" ? "已开始：识别 → 出方案 → 出分镜" : "已开始一键出片，约 7–9 分钟", { description: "进度看右下角" })
      if (r.job) watch(r.job, () => toast.success(until === "keyframes" ? "分镜出好了，请审核" : "成片出好了"))
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
          <div className="text-xs tracking-[0.25em] text-gold-ink">PRODUCT TVC</div>
          <h1 className="mt-1 text-3xl font-bold tracking-wide">产品图生视频</h1>
          <p className="mt-1 text-sm text-muted-foreground">一张产品图 → 3D 空间贴字广告分镜 → MiniMax H3 视频 → 15 秒竖屏成片</p>
        </div>
        <CloudBadge s={cloud} />
      </div>

      {/* 流程 */}
      <Stagger className="mt-6 grid grid-cols-2 gap-2.5 md:grid-cols-5">
        {[
          ["识别产品", "Qwen3-VL 看图"], ["写方案", "大模型按 TVC 规则"], ["出分镜", "Qwen-Image 2.1 × 4 张"],
          ["出视频段", "H3 首尾帧 × 3 段"], ["合成成片", "1080×1920 · 15 秒"],
        ].map(([t, d], i) => (
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
          onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]) }}
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
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        <div className="grid content-start gap-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm">产品名称 <span className="text-xs text-muted-foreground">必填，比自动识别更准</span>
              <Input value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} placeholder="例如：劳力士 GMT-Master II 黑圈" />
            </label>
            <label className="grid gap-1.5 text-sm">品牌名 <span className="text-xs text-muted-foreground">选填，会作为画面大字</span>
              <Input value={form.brand} onChange={(e) => setForm({ ...form, brand: e.target.value })} placeholder="例如：ROLEX" />
            </label>
          </div>
          <label className="grid gap-1.5 text-sm">核心卖点 <span className="text-xs text-muted-foreground">选填，会变成画面里的 3D 功能词</span>
            <Input value={form.selling_points} onChange={(e) => setForm({ ...form, selling_points: e.target.value })} placeholder="例如：两地时区、黑色陶瓷表圈、蚝式钢" />
          </label>
          <label className="grid gap-1.5 text-sm">风格 / 其他要求
            <Textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} rows={2} placeholder="例如：高级感、黑色影棚、节奏快一些" />
          </label>
          <div className="mt-1 flex flex-wrap gap-2">
            <Button size="lg" className="gold-gradient shine font-bold" disabled={busy} onClick={() => start("keyframes")}>
              {busy ? <Loader2 className="animate-spin" /> : <Wand2 />}生成分镜（先审核）
            </Button>
            <Button size="lg" variant="outline" disabled={busy} onClick={() => start("final")}><Rocket />一键直接出片</Button>
            <span className="self-center text-xs text-muted-foreground">分镜约 1 分钟；整条成片约 7–9 分钟</span>
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
                <div className="aspect-[9/16] bg-muted bg-cover bg-center" style={{ backgroundImage: p.cover ? `url('${tvcFile(p.id, p.cover)}')` : undefined }}>
                  {!p.cover && <div className="grid size-full place-items-center text-muted-foreground"><Sparkles className="size-6" /></div>}
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
