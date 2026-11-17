import { useCallback, useEffect, useRef, useState, type ReactNode } from "react"
import { Eye, ImageOff, Loader2, RefreshCw, RotateCcw, Save, Sparkles, Sun, Wand2 } from "lucide-react"
import { toast } from "sonner"

import { MediaFrame } from "@/components/feature-panel"
import { Button } from "@/components/ui/button"
import { useJobs } from "@/hooks/use-jobs"
import { api, urls, type LookSettings } from "@/lib/api"
import { cn } from "@/lib/utils"

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
 * batch：用哪个项目的画面预览、「重新出片」出哪个项目；没有项目时只能调参数，不能预览。
 */
export function BeautyEditor({ batch, scripts, header }: { batch: string | null; scripts: number; header?: ReactNode }) {
  const { watch } = useJobs()
  const [s, setS] = useState<LookSettings | null>(null)
  const [defaults, setDefaults] = useState<LookSettings | null>(null)
  const [saved, setSaved] = useState<LookSettings | null>(null)
  const [kind, setKind] = useState<Kind>("face")
  const [frameIdx, setFrameIdx] = useState<Record<Kind, number>>({ face: 0, watch: 0 })
  const [frameCount, setFrameCount] = useState(1)
  const [mode, setMode] = useState<Mode>("wipe")
  const [wipe, setWipe] = useState(50)
  const [hold, setHold] = useState(false)
  const [img, setImg] = useState<{ original: string; beauty: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const seq = useRef(0)

  useEffect(() => {
    api.getLook().then((r) => { setS(r.settings); setSaved(r.settings); setDefaults(r.defaults) }).catch(() => {})
  }, [])
  useEffect(() => {
    setImg(null)
    setError(null)
    setFrameIdx({ face: 0, watch: 0 })
  }, [batch])

  // 滑块一停就出新的对比图（等 350 毫秒，拖动过程中不连续请求）
  const refresh = useCallback(async (b: string, settings: LookSettings, k: Kind, index: number) => {
    const my = ++seq.current
    setLoading(true)
    try {
      const r = await api.lookPreview(b, k, settings, index)
      if (my !== seq.current) return
      setImg({ original: urls.lookFile(r.original), beauty: urls.lookFile(r.beauty) })
      setFrameCount(r.count || 1)
      setError(null)
    } catch (e) {
      if (my === seq.current) setError(String(e).replace(/^Error: /, ""))
    } finally {
      if (my === seq.current) setLoading(false)
    }
  }, [])
  useEffect(() => {
    if (!s || !batch) return
    const t = setTimeout(() => refresh(batch, s, kind, frameIdx[kind]), 350)
    return () => clearTimeout(t)
  }, [batch, s, kind, frameIdx, refresh])

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
              <span className="text-[11px] text-muted-foreground">不同天、不同地方拍的素材，先按老板的肤色把亮度和白平衡拉齐，再套美颜调色，成片效果一致。</span>
            </label>
            <div className="grid gap-5 px-1">
              <Slider label="磨皮" hint="跟随人脸局部磨皮，保护眼眉和嘴唇。0 关闭，50 是试片的力度。" value={s.smooth} onChange={(v) => set({ smooth: v })} disabled={!s.enabled} />
              <Slider label="提亮调色" hint="人脸提亮、背景变白、肤色偏粉。0 = 原片颜色，100 = 照参考视频调的" value={s.tone} onChange={(v) => set({ tone: v })} disabled={!s.enabled} />
              <Slider label="手表特写锐化" hint="只用在没有人脸的画面，钻石、表盘更清楚。0 = 不锐化" value={s.sharpen} onChange={(v) => set({ sharpen: v })} disabled={!s.enabled} />
            </div>
            <div className="flex flex-wrap items-center gap-2 border-t pt-5">
              <Button className="rounded-full bg-foreground text-background hover:bg-foreground/85" disabled={busy || !changed} onClick={() => save(false)}>
                {busy ? <Loader2 className="animate-spin" /> : <Save />}{changed ? "保存设置" : "已保存"}
              </Button>
              <Button variant="outline" className="rounded-full" disabled={busy || !batch || !scripts} onClick={() => save(true)}
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
          {!batch ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted-foreground">
              <div className="grid justify-items-center gap-2"><ImageOff className="size-6" />先上传素材，才能用素材里的画面预览</div>
            </div>
          ) : error && !img ? (
            <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-muted-foreground">
              <div className="grid justify-items-center gap-2"><ImageOff className="size-6" />{error}</div>
            </div>
          ) : (loading || !img) && (
            <div className="absolute inset-0 grid place-items-center bg-black/10"><Loader2 className="size-6 animate-spin text-white drop-shadow" /></div>
          )}
        </MediaFrame>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button size="sm" variant="ghost" className="rounded-full" disabled={!batch || loading || frameCount < 2}
            title="在这个项目的素材里挑好的几帧之间切换"
            onClick={() => setFrameIdx((x) => ({ ...x, [kind]: (x[kind] + 1) % Math.max(1, frameCount) }))}>
            <RefreshCw />换一帧{frameCount > 1 && <span className="text-muted-foreground tabular">{frameIdx[kind] % frameCount + 1}/{frameCount}</span>}
          </Button>
          <Button size="sm" variant="outline" className="rounded-full select-none" disabled={!img}
            onPointerDown={() => setHold(true)} onPointerUp={() => setHold(false)} onPointerLeave={() => setHold(false)}>
            <Eye />按住看原片
          </Button>
        </div>
        <p className="text-center text-xs text-muted-foreground">
          {mode === "wipe" ? "在画面上左右拖动，看原片和美颜后的区别" : "预览是这个项目素材里的一帧，按成片分辨率处理"}
        </p>
      </div>
    </div>
  )
}
