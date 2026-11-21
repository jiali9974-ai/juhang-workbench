import { useCallback, useEffect, useState, useSyncExternalStore, type ReactNode } from "react"
import { Eye, ImageOff, Loader2, RotateCcw, Save, Sparkles, Sun, Wand2 } from "lucide-react"
import { toast } from "sonner"

import { MediaFrame } from "@/components/feature-panel"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { api, urls, type LookSettings, type OutputVideo } from "@/lib/api"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"
import { previewCache } from "@/lib/background-tasks"
import defaultTestImage from "../../../assets/beauty-default.jpg"

type Kind = "face" | "watch"
type Mode = "beauty" | "original" | "wipe"

function Slider({ label, hint, value, onChange, disabled }: {
  label: string; hint: string; value: number; onChange: (v: number) => void; disabled?: boolean
}) {
  return (
    <label className={cn("grid gap-1.5", disabled && "opacity-45")}>
      <span className="flex items-baseline justify-between text-sm">
        <b className="font-medium">{label}</b>
        <span className="text-xs text-muted-foreground tabular">{Math.round(value * 100)}</span>
      </span>
      <input
        type="range" min={0} max={100} step={5} value={Math.round(value * 100)} disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value) / 100)}
        className="h-2 w-full cursor-pointer accent-[var(--foreground)]"
      />
      <span className="text-[11px] text-muted-foreground">{hint}</span>
    </label>
  )
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: [T, string][]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-full border p-0.5 text-xs">
      {options.map(([v, t]) => (
        <button key={v} onClick={() => onChange(v)}
          className={cn("rounded-full px-3 py-1 transition", value === v ? "bg-foreground font-medium text-background" : "text-muted-foreground hover:text-foreground")}>
          {t}
        </button>
      ))}
    </div>
  )
}

/**
 * 美颜调色：左边滑块调强度，右边实时看原片和美颜后的对比。保存后批量出片都用这个设置。
 * source：成片封面原图，null 使用独立的默认图；batch 仅用于「重新出片」。
 */
export function BeautyEditor({ batch, scripts, source, revision, header }: {
  batch: string | null; scripts: number; source: Pick<OutputVideo, "batch" | "id"> | null; revision: string; header?: ReactNode
}) {
  const { watch, active } = useJobs()
  const [s, setS] = useSessionState<LookSettings | null>("beauty.settings", null)
  const [defaults, setDefaults] = useSessionState<LookSettings | null>("beauty.defaults", null)
  const [saved, setSaved] = useSessionState<LookSettings | null>("beauty.saved", null)
  const [kind, setKind] = useSessionState<Kind>("beauty.kind", "face")
  const [mode, setMode] = useSessionState<Mode>("beauty.mode", "wipe")
  const [wipe, setWipe] = useSessionState("beauty.wipe", 50)
  const [hold, setHold] = useState(false)
  const [busy, setBusy] = useSessionState("beauty.saving", false)
  const rendering = active.some((job) => job.kind === "render" && batch && job.title.startsWith(`${batch}_`))
  const previewKey = s ? JSON.stringify(["beauty-source", source, revision, s, kind]) : null
  type PreviewResult = Awaited<ReturnType<typeof api.lookPreview>>
  const snapshot = useCallback(() => previewCache.get<PreviewResult>(previewKey), [previewKey])
  const preview = useSyncExternalStore(previewCache.subscribe, snapshot, snapshot)
  const img = preview.data ? {
    original: urls.lookFile(preview.data.original),
    beauty: urls.lookFile(preview.data.beauty),
  } : null
  const error = preview.error
  const loading = !!previewKey && (preview.status === "idle" || preview.status === "loading")

  useEffect(() => {
    if (s) return
    api.getLook().then((r) => { setS(r.settings); setSaved(r.settings); setDefaults(r.defaults) }).catch(() => {})
  }, [s, setS, setSaved, setDefaults])

  // 滑块一停就出新的对比图（等 350 毫秒，拖动过程中不连续请求）
  useEffect(() => {
    if (!s || !previewKey) return
    const t = setTimeout(() => previewCache.start(previewKey, () => api.lookPreview(source, kind, s)), 350)
    return () => clearTimeout(t)
  }, [source, s, kind, previewKey])

  const set = (patch: Partial<LookSettings>) => setS((x) => (x ? { ...x, ...patch } : x))
  const changed = !!s && !!saved && JSON.stringify(s) !== JSON.stringify(saved)

  async function save(rerender: boolean) {
    if (!s) return
    setBusy(true)
    try {
      const r = await api.saveLook(s)
      setSaved(r.settings)
      if (rerender && batch) {
        const jobs = await api.renderAll(batch, true)
        toast.success(`已保存，「${batch}」${jobs.length} 条成片开始按新美颜重新出片`, { description: "进度在右下角" })
        jobs.forEach((j) => watch(j, (job) => toast.success(`${job.title} 完成`)))
      } else {
        toast.success("美颜设置已保存", { description: "之后出片（单条或批量）都用这个强度" })
      }
    } catch (e) {
      toast.error("保存失败", { description: String(e).replace(/^Error: /, "") })
    } finally {
      setBusy(false)
    }
  }

  const showOriginal = hold || mode === "original"
  return (
    <div className="grid grid-cols-1 gap-10 lg:grid-cols-2 lg:items-start lg:gap-16">
      {/* 左：说明和强度 */}
      <div className="min-w-0">
        {header}
        {!s ? (
          <div className="grid h-40 place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>
        ) : (
          <div className="grid gap-5">
            <label className="flex cursor-pointer items-center justify-between rounded-xl border px-4 py-3 text-sm">
              <span className="flex items-center gap-2 font-medium"><Sparkles className="size-4" />开启美颜调色</span>
              <input type="checkbox" checked={s.enabled} onChange={(e) => set({ enabled: e.target.checked })} className="size-4 accent-[var(--foreground)]" />
            </label>
            <label className={cn("grid cursor-pointer gap-1 rounded-xl border px-4 py-3", !s.enabled && "opacity-45")}>
              <span className="flex items-center justify-between text-sm">
                <span className="flex items-center gap-2 font-medium"><Sun className="size-4" />统一光线</span>
                <input type="checkbox" checked={s.normalize} disabled={!s.enabled} onChange={(e) => set({ normalize: e.target.checked })} className="size-4 accent-[var(--foreground)]" />
              </span>
              <span className="text-[11px] text-muted-foreground">按每段光线温和校正曝光与白平衡，保留不同人物的肤色；手表特写保留产品原色。</span>
            </label>
            <div className="grid gap-5 px-1">
              <Slider label="磨皮" hint="跟随人脸局部磨皮，保护眼眉和嘴唇。0 关闭，50 是试片的力度。" value={s.smooth} onChange={(v) => set({ smooth: v })} disabled={!s.enabled} />
              <Slider label="提亮调色" hint="温和提亮中间调，保留肤色、服饰和产品色相。0 = 不额外调色" value={s.tone} onChange={(v) => set({ tone: v })} disabled={!s.enabled} />
              <Slider label="手表特写锐化" hint="只用在没有人脸的画面，钻石、表盘更清楚。0 = 不锐化" value={s.sharpen} onChange={(v) => set({ sharpen: v })} disabled={!s.enabled} />
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t pt-5">
              <Button className="rounded-full" disabled={busy || !changed} aria-busy={busy} onClick={() => save(false)}>
                {busy ? <Loader2 className="animate-spin" /> : <Save />}{changed ? "保存设置" : "已保存"}
              </Button>
              <Button variant="outline" className="rounded-full" disabled={busy || rendering || !batch || !scripts} aria-busy={busy || rendering} onClick={() => save(true)}
                title={batch ? `会覆盖「${batch}」现在的成片` : undefined}>
                <Wand2 />保存并重新出片{batch && scripts ? `（${batch} · ${scripts} 条）` : ""}
              </Button>
              <Button variant="ghost" size="sm" className="rounded-full text-muted-foreground" disabled={!defaults} onClick={() => defaults && setS(defaults)}>
                <RotateCcw />恢复默认
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* 右：对比预览 */}
      <div className="grid gap-3 lg:sticky lg:top-10">
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Segmented value={kind} onChange={setKind} options={[["face", "人脸画面"], ["watch", "手表特写"]]} />
          <Segmented value={mode} onChange={setMode} options={[["wipe", "左右对比"], ["beauty", "美颜后"], ["original", "原片"]]} />
        </div>
        <MediaFrame>
          {!img && !source && (
            <>
              <img src={defaultTestImage} className="absolute inset-0 size-full object-cover" alt="默认美颜测试图" draggable={false} />
              <span className="absolute top-2 left-2 rounded bg-black/55 px-1.5 text-[11px] text-white">原图</span>
            </>
          )}
          {img && (
            <>
              <img src={showOriginal ? img.original : img.beauty} className="absolute inset-0 size-full object-cover" draggable={false} alt="" />
              {mode === "wipe" && !hold && (
                <>
                  {/* 左边原片、右边美颜后，拖中间的线对比 */}
                  <img src={img.original} className="absolute inset-0 size-full object-cover" style={{ clipPath: `inset(0 ${100 - wipe}% 0 0)` }} draggable={false} alt="" />
                  <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-white shadow-[0_0_6px_rgba(0,0,0,.5)]" style={{ left: `${wipe}%` }} />
                  <span className="absolute top-2 left-2 rounded bg-black/55 px-1.5 text-[11px] text-white">原片</span>
                  <span className="absolute top-2 right-2 rounded bg-black/55 px-1.5 text-[11px] text-white">美颜后</span>
                  <input type="range" min={0} max={100} value={wipe} onChange={(e) => setWipe(Number(e.target.value))}
                    className="absolute inset-0 size-full cursor-ew-resize opacity-0" aria-label="拖动对比" />
                </>
              )}
              {(mode !== "wipe" || hold) && (
                <span className="absolute top-2 left-2 rounded bg-black/55 px-1.5 text-[11px] text-white">{showOriginal ? "原片" : "美颜后"}</span>
              )}
            </>
          )}
          {error && !img && source ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted-foreground">
              <div className="grid justify-items-center gap-2"><ImageOff className="size-6" />{error}</div>
            </div>
          ) : loading && (
            <div className="absolute right-3 bottom-3 rounded-full bg-black/50 p-2"><Loader2 className="size-4 animate-spin text-white" aria-label="正在计算美颜预览" /></div>
          )}
        </MediaFrame>
        {error && !img && !source && <p role="alert" className="text-center text-xs text-destructive">美颜预览失败：{error}</p>}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button size="sm" variant="outline" className="rounded-full select-none" disabled={!img}
            onPointerDown={() => setHold(true)} onPointerUp={() => setHold(false)} onPointerLeave={() => setHold(false)}>
            <Eye />按住看原片
          </Button>
        </div>
        <p className="text-center text-xs text-muted-foreground">
          {preview.data?.fallback ? "正在使用默认测试图" :
            mode === "wipe" ? "在画面上左右拖动，看原片和美颜后的区别" :
              source ? "封面抠图前的原图" : "默认测试图"}
        </p>
      </div>
    </div>
  )
}
