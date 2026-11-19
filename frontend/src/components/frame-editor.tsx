import { cloneElement, isValidElement, useCallback, useEffect, useId, useRef, useState, useSyncExternalStore, type ReactNode } from "react"
import { ArrowDown, ArrowUp, Check, Copy, Eye, EyeOff, Film, ImagePlus, Loader2, Pause, Play, Plus, RotateCcw, Save, SlidersHorizontal, Sparkles, Trash2, Type, Upload, X } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { MediaFrame } from "@/components/feature-panel"
import { GraphicsCanvas, StickerShape } from "@/components/graphics-canvas"
import { useSessionState } from "@/hooks/use-session-state"
import { useJobs } from "@/hooks/use-jobs"
import { api, urls, type LookSettings, type OutputVideo } from "@/lib/api"
import { previewCache } from "@/lib/background-tasks"
import { ANIMATIONS, STICKERS, makeElement, type GraphicElement, type GraphicsSettings, type EditorFont, type TextStyle } from "@/lib/graphics"
import { cn } from "@/lib/utils"
import defaultImage from "../../../assets/beauty-default.jpg"

interface EditorState {
  look: LookSettings; design: GraphicsSettings; fonts: EditorFont[]
  defaultLook: LookSettings; defaultDesign: GraphicsSettings; savedLook: LookSettings; savedDesign: GraphicsSettings
}
const inputClass = "h-9 w-full rounded-lg border bg-background px-2.5 text-sm tabular-nums outline-none focus:border-foreground/50"
const fontLoads = new Map<string, Promise<void>>()
function loadFont(font: EditorFont) {
  if (!fontLoads.has(font.id)) fontLoads.set(font.id, new FontFace(`jh-${font.id}`, `url(/api/fonts/${encodeURIComponent(font.id)}/file)`)
    .load().then((face) => { document.fonts.add(face) }).catch((error) => { fontLoads.delete(font.id); throw error }))
  return fontLoads.get(font.id)!
}
function Field({ label, children }: { label: string; children: ReactNode }) {
  const id = useId()
  return <div className="grid min-w-0 gap-1.5 text-xs text-muted-foreground"><label htmlFor={id}>{label}</label>{isValidElement<{ id?: string }>(children) ? cloneElement(children, { id }) : children}</div>
}
function NumberField({ label, value, onChange, min = 0, max = 100, step = 1 }: { label: string; value: number; onChange: (value: number) => void; min?: number; max?: number; step?: number }) {
  return <Field label={label}><input className={inputClass} type="number" min={min} max={max} step={step} value={Math.round(value * 100) / 100}
    onChange={(event) => { if (event.target.value !== "") onChange(Math.max(min, Math.min(max, Number(event.target.value)))) }} /></Field>
}
function Range({ label, value, onChange, disabled, hint }: { label: string; value: number; onChange: (v: number) => void; disabled?: boolean; hint: string }) {
  return <label className={cn("grid gap-2", disabled && "opacity-45")}><span className="flex justify-between text-sm font-medium">{label}<span className="text-xs text-muted-foreground">{Math.round(value * 100)}</span></span>
    <input className="w-full accent-[var(--foreground)]" type="range" min="0" max="100" step="5" disabled={disabled} value={value * 100} onChange={(e) => onChange(Number(e.target.value) / 100)} />
    <span className="text-xs leading-relaxed text-muted-foreground">{hint}</span></label>
}

export function FrameEditor({ batch, scripts, source, revision, header }: {
  batch: string | null; scripts: number; source: Pick<OutputVideo, "batch" | "id"> | null; revision: string; header: ReactNode
}) {
  const [editor, setEditor] = useSessionState<EditorState | null>("frame-editor.v1", null)
  const [tab, setTab] = useSessionState<"look" | "text" | "stickers">("frame-editor.tab", "text")
  const [selected, setSelected] = useSessionState("frame-editor.selected", "subtitle")
  const [loadError, setLoadError] = useState("")
  const [saving, setSaving] = useState(false)
  const [fontBusy, setFontBusy] = useState(false)
  const [fontError, setFontError] = useState("")
  const [managedFont, setManagedFont] = useState("")
  const [hold, setHold] = useState(false)
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const timeRef = useRef(0)
  const [previewBusy, setPreviewBusy] = useState(false)
  const [video, setVideo] = useState("")
  const videoDialog = useRef<HTMLDialogElement>(null)
  const fontInput = useRef<HTMLInputElement>(null)
  const { watch, active } = useJobs()
  useEffect(() => {
    const dialog = videoDialog.current
    if (video && dialog && !dialog.open) dialog.showModal()
    if (!video && dialog?.open) dialog.close()
  }, [video])
  const rendering = active.some((job) => batch && job.title.startsWith(batch) && (job.kind === "render" || job.kind === "auto"))
  const fetchState = useCallback(() => {
    return Promise.all([api.getLook(), api.getGraphics()]).then(([look, design]) => {
      setEditor({ look: look.settings, design: design.settings, fonts: design.fonts, defaultLook: look.defaults, defaultDesign: design.defaults,
        savedLook: look.settings, savedDesign: design.settings })
    }).catch((e: unknown) => setLoadError(String(e).replace(/^Error: /, "")))
  }, [setEditor])
  useEffect(() => { if (!editor) void fetchState() }, [editor, fetchState])
  const fontList = editor?.fonts
  useEffect(() => {
    if (!fontList) return
    let live = true
    Promise.all(fontList.map(loadFont)).then(() => { if (live) setFontError("") })
      .catch(() => { if (live) setFontError("字体预览加载失败，请检查网络后重试") })
    return () => { live = false }
  }, [fontList])

  const timeline = Math.max(6, ...(editor?.design.elements.map((item) => item.end ?? item.start + 6) ?? []))
  useEffect(() => {
    if (!playing) return
    const start = performance.now() - timeRef.current * 1000
    let frame = 0
    const tick = (now: number) => { const next = ((now - start) / 1000) % timeline; timeRef.current = next; setTime(next); frame = requestAnimationFrame(tick) }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [playing, timeline])
  const seek = (value: number) => { setPlaying(false); timeRef.current = value; setTime(value) }

  type Preview = Awaited<ReturnType<typeof api.lookPreview>>
  const previewKey = editor ? JSON.stringify(["frame-background", source, revision, editor.look]) : null
  const snapshot = useCallback(() => previewCache.get<Preview>(previewKey), [previewKey])
  const preview = useSyncExternalStore(previewCache.subscribe, snapshot, snapshot)
  const lookSettings = editor?.look
  useEffect(() => {
    if (!lookSettings || !previewKey) return
    const timer = setTimeout(() => previewCache.start(previewKey, () => api.lookPreview(source, "face", lookSettings)), 350)
    return () => clearTimeout(timer)
  }, [previewKey, lookSettings, source])

  const changeDesign = (fn: (settings: GraphicsSettings) => GraphicsSettings) => setEditor((current) => current ? { ...current, design: fn(current.design) } : current)
  const update = (patch: Partial<GraphicElement> & Partial<TextStyle>, id = selected) => changeDesign((settings) => id === "subtitle"
    ? { ...settings, subtitle: { ...settings.subtitle, ...patch } }
    : { ...settings, elements: settings.elements.map((item) => item.id === id ? { ...item, ...patch } : item) })
  const changeLook = (patch: Partial<LookSettings>) => setEditor((current) => current ? { ...current, look: { ...current.look, ...patch } } : current)
  const element = editor?.design.elements.find((item) => item.id === selected)
  const layer = selected === "subtitle" ? editor?.design.subtitle : element
  const changed = !!editor && (JSON.stringify(editor.look) !== JSON.stringify(editor.savedLook) || JSON.stringify(editor.design) !== JSON.stringify(editor.savedDesign))
  function choose(id: string) { setSelected(id); const item = editor?.design.elements.find((layer) => layer.id === id); if (item) seek(item.start) }
  function add(type: "text" | "sticker", icon: GraphicElement["icon"] = "arrow") {
    if (!editor) return
    if (editor.design.elements.length >= 30) { toast.error("最多添加 30 个画面元素"); return }
    const item = makeElement(editor.design.subtitle, type, icon)
    changeDesign((settings) => ({ ...settings, elements: [...settings.elements, item] })); setSelected(item.id); seek(0)
  }
  function remove() {
    changeDesign((settings) => ({ ...settings, elements: settings.elements.filter((item) => item.id !== selected) })); setSelected("subtitle")
  }
  function duplicate() {
    if (!element || !editor || editor.design.elements.length >= 30) return
    const copy = { ...element, id: crypto.randomUUID(), x: Math.min(95, element.x + 3), y: Math.min(95, element.y + 3) }
    changeDesign((settings) => ({ ...settings, elements: [...settings.elements, copy] })); choose(copy.id); setSelected(copy.id); seek(copy.start)
  }
  function reorder(direction: number) {
    changeDesign((settings) => {
      const index = settings.elements.findIndex((item) => item.id === selected), next = index + direction
      if (index < 0 || next < 0 || next >= settings.elements.length) return settings
      const items = [...settings.elements]; [items[index], items[next]] = [items[next], items[index]]
      return { ...settings, elements: items }
    })
  }
  async function save(rerender = false) {
    if (!editor) return
    setSaving(true)
    try {
      const design = await api.saveGraphics(editor.design), look = await api.saveLook(editor.look)
      setEditor((current) => current ? { ...current, design: current.design === editor.design ? design.settings : current.design,
        look: current.look === editor.look ? look.settings : current.look, savedDesign: design.settings, savedLook: look.settings } : current)
      if (rerender && batch) {
        const jobs = await api.renderAll(batch, true)
        jobs.forEach((job) => watch(job, (done) => toast.success(`${done.title} 完成`)))
        toast.success(`已保存，「${batch}」${jobs.length} 条视频开始重新出片`)
      } else toast.success("画面设置已保存", { description: "之后的单条和批量出片都会使用这些设置" })
    } catch (error) { toast.error("保存失败", { description: String(error).replace(/^Error: /, "") }) }
    finally { setSaving(false) }
  }
  async function upload(file?: File) {
    if (!file) return
    setFontBusy(true)
    try {
      const result = await api.uploadFont(file)
      setEditor((current) => current ? { ...current, fonts: result.fonts } : current)
      update({ font_id: result.font.id }); setManagedFont(result.font.id)
      toast.success("字体已添加，可以用于字幕和文字")
    } catch (e) { toast.error("添加字体失败", { description: String(e).replace(/^Error: /, "") }) }
    finally { setFontBusy(false); if (fontInput.current) fontInput.current.value = "" }
  }
  async function deleteFont() {
    if (!managedFont) return
    setFontBusy(true)
    try {
      const result = await api.deleteFont(managedFont)
      setEditor((current) => current ? { ...current, fonts: result.fonts } : current); setManagedFont(""); toast.success("字体已删除")
    } catch (e) { toast.error("删除字体失败", { description: String(e).replace(/^Error: /, "") }) }
    finally { setFontBusy(false) }
  }
  async function renderPreview() {
    if (!editor) return
    setPreviewBusy(true)
    try { const result = await api.graphicsPreview(editor.design, source, editor.look); setVideo(result.url) }
    catch (e) { toast.error("生成预览失败", { description: String(e).replace(/^Error: /, "") }) }
    finally { setPreviewBusy(false) }
  }

  return <>
    {header}
    <div className="mb-8 flex flex-wrap items-center justify-between gap-4 border-b pb-4">
      <div className="inline-flex gap-1 rounded-full bg-muted p-1" role="tablist" aria-label="画面编辑功能">
        {([["look", "画面调整", SlidersHorizontal], ["text", "文字与字幕", Type], ["stickers", "动画标识", Sparkles]] as const).map(([key, label, Icon]) =>
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)} className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-2 text-xs whitespace-nowrap transition sm:gap-2 sm:px-3 sm:text-sm", tab === key ? "bg-background font-medium shadow-sm" : "text-muted-foreground hover:text-foreground")}><Icon className="size-4 shrink-0" />{label}</button>)}
      </div>
      <span className="text-xs text-muted-foreground">{changed ? "有未保存的修改" : "已保存的设置用于后续出片"}</span>
    </div>
    {!editor ? <div className="grid min-h-64 place-items-center">{loadError ? <div role="alert" className="grid justify-items-center gap-3 text-sm text-destructive">{loadError}<Button variant="outline" onClick={() => { setLoadError(""); void fetchState() }}>重新加载</Button></div> : <Loader2 className="animate-spin" />}</div> :
      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,.95fr)] lg:gap-14">
        <div className="order-2 grid min-w-0 gap-5 lg:order-1">
          {tab === "look" ? <section className="grid gap-6 rounded-2xl border p-5">
            <div><h2 className="text-lg font-semibold">自然、干净的画面</h2><p className="mt-1 text-xs text-muted-foreground">保留原来的美颜、提亮与特写锐化。</p></div>
            <label className="flex items-center justify-between text-sm">开启美颜调色<input type="checkbox" className="size-4 accent-[var(--foreground)]" checked={editor.look.enabled} onChange={(e) => changeLook({ enabled: e.target.checked })} /></label>
            <label className="flex items-center justify-between text-sm">统一不同素材的光线<input type="checkbox" className="size-4 accent-[var(--foreground)]" disabled={!editor.look.enabled} checked={editor.look.normalize} onChange={(e) => changeLook({ normalize: e.target.checked })} /></label>
            <Range label="磨皮" value={editor.look.smooth} onChange={(smooth) => changeLook({ smooth })} disabled={!editor.look.enabled} hint="局部柔化肤质，保护眼眉和嘴唇。" />
            <Range label="提亮调色" value={editor.look.tone} onChange={(tone) => changeLook({ tone })} disabled={!editor.look.enabled} hint="提升亮度，保留自然肤色和高光。" />
            <Range label="手表特写锐化" value={editor.look.sharpen} onChange={(sharpen) => changeLook({ sharpen })} disabled={!editor.look.enabled} hint="作用于没有人脸的特写画面。" />
          </section> : <>
            <section className="rounded-2xl border p-4">
              <div className="mb-3 flex items-center justify-between"><h2 className="font-semibold">{tab === "text" ? "画面文字" : "动态标识"}</h2>
                {tab === "text" && <Button size="sm" variant="outline" className="rounded-full" onClick={() => add("text")}><Plus />添加文字</Button>}</div>
              {tab === "stickers" && <div className="mb-4 grid grid-cols-3 gap-2">{STICKERS.map(([key, name, color]) =>
                <button key={key} onClick={() => add("sticker", key)} aria-label={`添加${name}`} className="grid justify-items-center gap-2 rounded-xl border bg-muted/30 p-3 text-xs transition hover:border-foreground/40 hover:bg-muted"><span className="block size-9"><StickerShape icon={key} color={color} /></span>{name}</button>)}</div>}
              <div className="grid gap-1.5" aria-label="画面图层">
                <button className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm", selected === "subtitle" ? "bg-foreground text-background" : "bg-muted/50")} onClick={() => choose("subtitle")}><Type className="size-4 shrink-0" /><span className="flex-1">口播字幕</span>{!editor.design.subtitle.enabled && <EyeOff className="size-3.5" />}</button>
                {editor.design.elements.filter((item) => tab === "text" ? item.type === "text" : item.type === "sticker").map((item) =>
                  <button key={item.id} className={cn("flex items-center gap-2 rounded-lg px-3 py-2 text-left text-sm", selected === item.id ? "bg-foreground text-background" : "bg-muted/50")} onClick={() => choose(item.id)}>
                    {item.type === "text" ? <Type className="size-4 shrink-0" /> : <Sparkles className="size-4 shrink-0" />}<span className="min-w-0 flex-1 truncate">{item.text || (item.type === "sticker" ? STICKERS.find(([key]) => key === item.icon)?.[1] : "未命名文字")}</span>{!item.enabled && <EyeOff className="size-3.5" />}
                  </button>)}
                {editor.design.elements.filter((item) => item.type === (tab === "text" ? "text" : "sticker")).length === 0 && <p className="px-1 pt-3 text-xs text-muted-foreground">{tab === "text" ? "添加标题、门店名称或提示语，再拖到合适的位置。" : "选择上方标识添加到画面，点击图层即可修改。"}</p>}
              </div>
            </section>
            {layer && <section className="grid gap-4 rounded-2xl border p-5" aria-label="选中元素属性">
              <div className="flex items-center justify-between"><h3 className="font-semibold">{selected === "subtitle" ? "口播字幕样式" : element?.type === "text" ? "编辑文字" : "编辑标识"}</h3><label className="flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={layer.enabled} onChange={(e) => update({ enabled: e.target.checked })} />显示</label></div>
              {selected === "subtitle" ? <p className="text-xs leading-relaxed text-muted-foreground">预览中的字幕是示例；出片时会使用剪辑脚本里的实际字幕内容。</p> :
                (element?.type === "text" || element?.icon === "badge") && <Field label="文字内容"><textarea className={`${inputClass} h-20 resize-y py-2`} maxLength={300} value={element.text} onChange={(e) => update({ text: e.target.value })} placeholder="输入要显示的文字，回车换行" /></Field>}
              {(selected === "subtitle" || element?.type === "text" || element?.icon === "badge") && <div className="grid grid-cols-[1fr_auto] items-end gap-3"><Field label="字体"><select className={inputClass} value={layer.font_id} onChange={(e) => update({ font_id: e.target.value })}>{editor.fonts.map((font) => <option key={font.id} value={font.id}>{font.name}</option>)}</select></Field><Button size="sm" variant={layer.bold ? "secondary" : "outline"} aria-pressed={layer.bold} onClick={() => update({ bold: !layer.bold })} className="h-9 font-bold">加粗</Button></div>}
              <div className="grid grid-cols-2 gap-3"><NumberField label={element?.type === "sticker" ? "标识大小" : "字号"} value={layer.size} min={16} max={600} onChange={(size) => update({ size })} />
                <Field label="颜色"><input type="color" className={`${inputClass} cursor-pointer p-1`} value={layer.color} onChange={(e) => update({ color: e.target.value })} /></Field></div>
              <input aria-label="调整大小" className="w-full accent-[var(--foreground)]" type="range" min={16} max={600} value={layer.size} onChange={(e) => update({ size: Number(e.target.value) })} />
              <div className="grid grid-cols-2 gap-3"><NumberField label="水平位置（%）" value={layer.x} onChange={(x) => update({ x })} step={.1} /><NumberField label="垂直位置（%）" value={layer.y} onChange={(y) => update({ y })} step={.1} /></div>
              {(selected === "subtitle" || element?.type === "text") && <div className="grid grid-cols-2 gap-3"><NumberField label="描边粗细" value={layer.outline} max={20} onChange={(outline) => update({ outline })} /><Field label="描边颜色"><input className={`${inputClass} p-1`} type="color" value={layer.outline_color} onChange={(e) => update({ outline_color: e.target.value })} /></Field></div>}
              {element && <>
                <div className="grid grid-cols-2 gap-3"><Field label="动画效果"><select className={inputClass} value={element.animation} onChange={(e) => update({ animation: e.target.value as GraphicElement["animation"] })}>{ANIMATIONS.map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></Field><NumberField label="旋转角度" min={-180} max={180} value={element.rotation} onChange={(rotation) => update({ rotation })} /></div>
                <div className="grid grid-cols-2 gap-3"><NumberField label="开始时间（秒）" max={86400} step={.1} value={element.start} onChange={(start) => update({ start, end: element.end !== null && element.end <= start ? start + 1 : element.end })} /><NumberField label="结束时间（秒）" max={86400} min={element.start + .1} step={.1} value={element.end ?? Math.max(6, element.start + 3)} onChange={(end) => update({ end })} /></div>
                <label className="flex items-center gap-2 text-xs text-muted-foreground"><input type="checkbox" checked={element.end === null} onChange={(e) => update({ end: e.target.checked ? null : element.start + 3 })} />一直显示到视频结束</label>
                <div className="flex flex-wrap gap-2 border-t pt-4"><Button variant="outline" size="sm" onClick={duplicate}><Copy />复制</Button><Button variant="outline" size="sm" onClick={() => reorder(-1)} title="移到下一层"><ArrowDown />下一层</Button><Button variant="outline" size="sm" onClick={() => reorder(1)} title="移到上一层"><ArrowUp />上一层</Button><Button variant="ghost" size="sm" className="ml-auto text-destructive" onClick={remove}><Trash2 />删除</Button></div>
              </>}
            </section>}
            {tab === "text" && <details className="rounded-2xl border p-4"><summary className="cursor-pointer text-sm font-medium">字体库 · {editor.fonts.length} 款字体</summary><div className="mt-4 grid gap-3">
              <p className="text-xs leading-relaxed text-muted-foreground">内置字体可直接使用。上传自己的 TTF / OTF 字体后，字幕和文字都能选择它。</p><input ref={fontInput} type="file" accept=".ttf,.otf" className="hidden" onChange={(event) => void upload(event.target.files?.[0])} aria-label="上传字体文件" />
              <Button variant="outline" size="sm" disabled={fontBusy} onClick={() => fontInput.current?.click()}>{fontBusy ? <Loader2 className="animate-spin" /> : <Upload />}添加字体</Button>
              {editor.fonts.some((font) => !font.builtin) && <div className="flex gap-2"><select className={inputClass} aria-label="选择要删除的字体" value={managedFont} onChange={(e) => setManagedFont(e.target.value)}><option value="">选择上传的字体</option>{editor.fonts.filter((font) => !font.builtin).map((font) => <option value={font.id} key={font.id}>{font.name}</option>)}</select><Button variant="outline" size="icon" aria-label="删除所选字体" disabled={fontBusy || !managedFont || !!layer && layer.font_id === managedFont} onClick={() => void deleteFont()}><Trash2 /></Button></div>}
            </div></details>}
          </>}
          <div className="flex flex-wrap gap-2 border-t pt-4"><Button className="rounded-full" disabled={saving || !changed} onClick={() => void save()}>{saving ? <Loader2 className="animate-spin" /> : changed ? <Save /> : <Check />}{changed ? "保存设置" : "已保存"}</Button>
            <Button className="rounded-full" variant="outline" disabled={saving || rendering || !batch || !scripts} onClick={() => void save(true)}><Film />保存并重新出片{batch && scripts ? `（${scripts} 条）` : ""}</Button>
            <Button variant="ghost" size="sm" disabled={saving} onClick={() => { setEditor({ ...editor, look: editor.defaultLook, design: editor.defaultDesign }); setSelected("subtitle"); seek(0) }}><RotateCcw />恢复默认</Button></div>
          <p className="text-xs leading-relaxed text-muted-foreground">这些设置用于之后的单条和批量出片。已有成片可点「保存并重新出片」更新{batch ? `「${batch}」` : "当前项目"}。</p>
        </div>
        <div className="order-1 grid gap-3 lg:order-2 lg:sticky lg:top-6">
          <div className="flex items-center justify-between text-xs text-muted-foreground"><span className="flex items-center gap-1.5"><ImagePlus className="size-3.5" />{source ? "使用所选成片的原始画面" : "默认测试画面"}</span><span>9:16</span></div>
          <div className="mx-auto w-full max-w-[calc(48svh*9/16)] lg:max-w-none"><MediaFrame>
            <img className="absolute inset-0 size-full object-cover" draggable={false} alt={hold ? "原始画面" : "画面编辑预览"} src={preview.data ? urls.lookFile(hold ? preview.data.original : preview.data.beauty) : defaultImage} />
            {!hold && <GraphicsCanvas settings={editor.design} fonts={editor.fonts} selected={selected} onSelect={(id) => { setSelected(id); setTab(id === "subtitle" || editor.design.elements.find((item) => item.id === id)?.type === "text" ? "text" : "stickers") }} onMove={(id, x, y) => update({ x, y }, id)} time={time} editing={!playing} />}
            {(preview.status === "loading" || preview.status === "idle") && <div className="pointer-events-none absolute right-3 bottom-3 rounded-full bg-black/50 p-2"><Loader2 className="size-4 animate-spin text-white" aria-label="更新背景预览" /></div>}
          </MediaFrame></div>
          <div className="flex items-center gap-3"><Button variant="outline" size="icon" className="shrink-0 rounded-full" aria-label={playing ? "暂停动画" : "播放动画"} onClick={() => setPlaying(!playing)}>{playing ? <Pause /> : <Play />}</Button><input className="min-w-0 flex-1 accent-[var(--foreground)]" type="range" min={0} max={timeline} step={.05} value={time} onChange={(e) => seek(Number(e.target.value))} aria-label="预览时间" /><span className="w-20 text-right text-xs tabular-nums text-muted-foreground">{time.toFixed(1)} / {timeline.toFixed(1)}s</span></div>
          <div className="flex flex-wrap justify-center gap-2"><Button variant="outline" size="sm" className="rounded-full" onPointerDown={() => setHold(true)} onPointerUp={() => setHold(false)} onPointerLeave={() => setHold(false)} onPointerCancel={() => setHold(false)}><Eye />按住看原片</Button><Button variant="outline" size="sm" className="rounded-full" disabled={previewBusy} onClick={() => void renderPreview()}>{previewBusy ? <Loader2 className="animate-spin" /> : <Film />}生成前 6 秒预览</Button></div>
          <p className="text-center text-xs text-muted-foreground">拖动画面中的文字或标识调整位置，选中后也可用方向键微调。</p>
          {(fontError || preview.error) && <p role="alert" className="text-center text-xs text-destructive">{fontError || preview.error}</p>}
        </div>
      </div>}
    <dialog ref={videoDialog} aria-label="实际渲染效果预览" onClose={() => setVideo("")} onClick={(event) => { if (event.target === event.currentTarget) setVideo("") }} className="fixed inset-0 m-auto max-h-[90svh] w-[calc(100%-2.5rem)] max-w-sm rounded-2xl border bg-background p-4 text-foreground shadow-xl backdrop:bg-black/65">
      {video && <><div className="mb-3 flex items-center justify-between text-sm font-medium">前 6 秒 · 实际渲染预览<Button variant="ghost" size="icon" aria-label="关闭预览" onClick={() => setVideo("")}><X /></Button></div><video className="max-h-[74svh] w-full rounded-lg" src={video} controls autoPlay loop playsInline /><p className="mt-2 text-center text-xs text-muted-foreground">示例画面和字幕，用于检查文字、位置及动画。</p></>}
    </dialog>
  </>
}
