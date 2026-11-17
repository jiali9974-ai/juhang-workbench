import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowDown, ArrowLeft, ArrowUp, AudioLines, Download, Film, GripVertical, Keyboard, Loader2, Mic, Play, Save, Shuffle, Trash2, Video, Wand2, X } from "lucide-react"
import { AnimatePresence, motion, Reorder, useDragControls } from "motion/react"
import { toast } from "sonner"

import { LangTag, Phone, StatusBadge } from "@/components/bits"
import { ease } from "@/components/motion"
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { Textarea } from "@/components/ui/textarea"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useJobs } from "@/hooks/use-jobs"
import { followTask, getRoute, go } from "@/hooks/use-route"
import { useSessionState } from "@/hooks/use-session-state"
import { api, urls, type Line, type Role, type Script, type TtsEngine, type VoiceMode, type VoiceRef } from "@/lib/api"
import { lineDuration, resolvedVoice, ROLE, scriptDuration, shortClip, subtitleChars, subtitleTooLong, tsec, VOICE } from "@/lib/format"
import { cn } from "@/lib/utils"

type Preview = { kind: "none" } | { kind: "output" } | { kind: "source"; key: string }

const ZOOMS = [
  { v: "auto", label: "自动放大" },
  { v: "1", label: "不放大" },
  { v: "1.15", label: "×1.15" },
  { v: "1.25", label: "×1.25" },
  { v: "1.4", label: "×1.4" },
]

let keySeq = 0
const newKey = () => `l${++keySeq}`

const isTyping = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable || t.getAttribute("role") === "combobox")

export function ScriptEditor({ batch, id }: { batch: string; id: string }) {
  const { watch, active } = useJobs()
  const [script, setScript] = useState<Script | null>(null)
  // 每句一个稳定的 key，拖动排序和删除动画都靠它
  const [keys, setKeys] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  const [savedAt, setSavedAt] = useState("")
  const [current, setCurrent] = useState<string | null>(null)
  const [preview, setPreview] = useState<Preview>({ kind: "none" })
  const [outVer, setOutVer] = useState(() => Date.now())
  const [ttsLoading, setTtsLoading] = useSessionState<string | null>(`script.tts:${batch}:${id}`, null)
  const [engines, setEngines] = useState<{ default: string; engines: TtsEngine[] } | null>(null)
  useEffect(() => {
    api.ttsEngines().then(setEngines).catch(() => {})
  }, [])
  const [refCands, setRefCands] = useState<VoiceRef[]>([])
  useEffect(() => {
    api.voiceRef(batch, id).then((r) => {
      setRefCands(r.candidates)
      // 还没选过原声片段时，先用排第一的那段
      setScript((s) => (s && !s.voice_ref && r.current ? { ...s, voice_ref: r.current } : s))
    }).catch(() => {})
  }, [batch, id])
  const audio = useRef<HTMLAudioElement>(null)

  const load = useCallback(async () => {
    const list = await api.scripts(batch)
    let s = list.find((x) => x.id === id) ?? null
    // 老板原声参考：还没选过就先用排第一的那段（脚本加载完再取，避免先后顺序丢数据）
    const refs = s ? await api.voiceRef(batch, id).catch(() => null) : null
    setRefCands(refs?.candidates ?? [])
    if (s && !s.voice_ref && refs?.current) s = { ...s, voice_ref: refs.current }
    setScript(s)
    setKeys(s ? s.lines.map(() => newKey()) : [])
    setDirty(false)
    setOutVer(Date.now())
    if (s?.has_output) setPreview({ kind: "output" })
  }, [batch, id])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const on = (e: BeforeUnloadEvent) => {
      if (dirty) e.preventDefault()
    }
    window.addEventListener("beforeunload", on)
    return () => window.removeEventListener("beforeunload", on)
  }, [dirty])

  const touch = () => setDirty(true)
  const update = (fn: (s: Script) => Script) => {
    setScript((s) => (s ? fn(structuredClone(s)) : s))
    touch()
  }
  const updateLine = (i: number, patch: Partial<Line>) =>
    update((s) => {
      s.lines[i] = { ...s.lines[i], ...patch }
      return s
    })

  const save = useCallback(
    async (status?: Script["status"], quiet = false) => {
      if (!script) return
      const clean: Script = { ...script, status: status ?? script.status }
      delete clean.duration
      delete clean.resolved_voice
      delete clean.has_output
      await api.saveScript(clean)
      setScript((s) => (s ? { ...s, status: clean.status } : s))
      setDirty(false)
      setSavedAt(new Date().toLocaleTimeString())
      if (!quiet) toast.success("已保存")
    },
    [script],
  )

  /** 按新的 key 顺序重排句子 */
  const applyOrder = useCallback(
    (next: string[]) => {
      setScript((s) => {
        if (!s) return s
        const byKey = new Map(keys.map((k, i) => [k, s.lines[i]]))
        return { ...s, lines: next.map((k) => byKey.get(k)!).filter(Boolean) }
      })
      setKeys(next)
      touch()
    },
    [keys],
  )

  const move = useCallback(
    (k: string, d: number) => {
      const i = keys.indexOf(k)
      const j = i + d
      if (i < 0 || j < 0 || j >= keys.length) return
      const next = [...keys]
      ;[next[i], next[j]] = [next[j], next[i]]
      applyOrder(next)
    },
    [keys, applyOrder],
  )

  const showSource = useCallback((k: string) => {
    setCurrent(k)
    setPreview({ kind: "source", key: k })
  }, [])

  // 键盘：Ctrl+S 保存；↑↓ 切换句子；Alt+↑↓ 调整顺序；空格看原片
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "s") {
        e.preventDefault()
        save()
        return
      }
      if (isTyping(e.target) || !keys.length) return
      const i = current ? keys.indexOf(current) : -1
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault()
        const d = e.key === "ArrowDown" ? 1 : -1
        if (e.altKey && current) return move(current, d)
        const k = keys[Math.max(0, Math.min(keys.length - 1, i + d))]
        setCurrent(k)
        document.getElementById(`line-${k}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
      } else if (e.key === " " && current) {
        e.preventDefault()
        showSource(current)
      }
    }
    window.addEventListener("keydown", on)
    return () => window.removeEventListener("keydown", on)
  }, [save, keys, current, move, showSource])

  if (!script) {
    return (
      <div className="mx-auto max-w-[1400px] space-y-3 px-8 pt-8">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-9 w-full" />
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24" />)}
      </div>
    )
  }

  const s = script
  const voice = resolvedVoice(s)
  const rendering = active.some((j) => j.title.startsWith(s.id))
  const lineOf = (k: string) => s.lines[keys.indexOf(k)]

  async function renderNow() {
    const source = getRoute()
    await save("approved", true)
    const j = await api.render(batch, s.id)
    toast("已确认，加入出片队列")
    watch(j, () => toast.success(`${s.id} 出片完成`))
    followTask(source, batch, j.id)
  }

  async function playTts(k: string) {
    setTtsLoading(k)
    try {
      const j = await api.ttsPreview(lineOf(k).subtitle, s.tts_engine || engines?.default, { batch, script_id: s.id, voice_source: s.voice_source ?? "original", voice_ref: s.voice_ref })
      watch(j, (job) => {
        setTtsLoading(null)
        if (audio.current) {
          audio.current.src = urls.ttsFile(job.result as string)
          audio.current.play()
        }
      })
    } catch (e) {
      setTtsLoading(null)
      toast.error("配音失败", { description: String(e) })
    }
  }

  function remove(k: string) {
    const i = keys.indexOf(k)
    const removed = s.lines[i]
    setScript({ ...s, lines: s.lines.filter((_, x) => x !== i) })
    setKeys(keys.filter((x) => x !== k))
    touch()
    toast(`已删除第 ${i + 1} 句`, {
      description: removed.subtitle,
      action: {
        label: "撤销",
        onClick: () => {
          setScript((cur) => (cur ? { ...cur, lines: [...cur.lines.slice(0, i), removed, ...cur.lines.slice(i)] } : cur))
          setKeys((cur) => [...cur.slice(0, i), k, ...cur.slice(i)])
        },
      },
    })
  }

  async function del() {
    await api.deleteScript(batch, s.id)
    toast("已删除脚本")
    go({ page: "batch", batch, tab: "scripts" })
  }

  function back() {
    if (dirty && !confirm("有未保存的修改，确定返回？")) return
    go({ page: "batch", batch, tab: "scripts" })
  }

  const pvLine = preview.kind === "source" ? lineOf(preview.key) : null
  const pvIndex = preview.kind === "source" ? keys.indexOf(preview.key) : -1

  return (
    <div className="mx-auto w-full max-w-[1480px] px-6 pt-5 pb-40 md:px-8">
      <button onClick={back} className="group mb-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground">
        <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />返回 {batch}
      </button>

      {/* 标题 + 配音模式 */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={s.title}
          onChange={(e) => update((x) => ({ ...x, title: e.target.value }))}
          className="-ml-2 min-w-[260px] flex-1 rounded-lg border border-transparent bg-transparent px-2 py-1 text-2xl font-bold outline-none transition-colors hover:border-border focus:border-primary focus:bg-card"
        />
        <StatusBadge status={s.status} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <span className="text-sm text-muted-foreground">配音</span>
        <ToggleGroup type="single" variant="outline" size="sm" value={s.voice_mode} onValueChange={(v) => v && update((x) => ({ ...x, voice_mode: v as VoiceMode }))}>
          {(Object.keys(VOICE) as VoiceMode[]).map((k) => (
            <ToggleGroupItem key={k} value={k} className="px-3 data-[state=on]:bg-primary/15 data-[state=on]:text-gold-ink">{VOICE[k]}</ToggleGroupItem>
          ))}
        </ToggleGroup>
        <AnimatePresence mode="wait" initial={false}>
          <motion.span
            key={voice + s.voice_mode}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18 }}
            className="text-xs text-muted-foreground"
          >
            {voice === "tts_all" ? `整条用粤语配音${s.voice_mode === "auto" ? "（有普通话句子）" : ""}` : "保留老板原声"}
          </motion.span>
        </AnimatePresence>
        {voice === "tts_all" && engines && (
          <motion.div initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">引擎</span>
            <Select value={s.tts_engine || engines.default} onValueChange={(v) => update((x) => ({ ...x, tts_engine: v }))}>
              <SelectTrigger size="sm" className="w-[150px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                {engines.engines.map((en) => (
                  <SelectItem key={en.id} value={en.id} disabled={!en.available}>
                    <span className={cn("size-1.5 rounded-full", en.available ? "bg-ok" : "bg-muted-foreground/40")} />
                    {en.name}
                    {!en.available && <span className="text-[11px] text-muted-foreground">（{en.note}）</span>}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </motion.div>
        )}
        <span className="ml-auto text-sm text-muted-foreground tabular">{s.lines.length} 句 · 原声约 {scriptDuration(s).toFixed(1)} 秒</span>
      </div>

      {/* 配音音色：老板原声克隆 / 固定音色 */}
      <AnimatePresence initial={false}>
        {voice === "tts_all" && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.25, ease }}
            className="overflow-hidden"
          >
            <div className="soft-shadow mt-3 flex flex-wrap items-center gap-3 rounded-xl border bg-card px-3 py-2.5">
              <span className="flex items-center gap-1.5 text-sm text-muted-foreground"><Mic className="size-4" />音色</span>
              <ToggleGroup
                type="single"
                variant="outline"
                size="sm"
                value={s.voice_source ?? "original"}
                onValueChange={(v) => v && update((x) => ({ ...x, voice_source: v as "original" | "fixed" }))}
              >
                <ToggleGroupItem value="original" className="px-3 data-[state=on]:bg-primary/15 data-[state=on]:text-gold-ink">老板原声</ToggleGroupItem>
                <ToggleGroupItem value="fixed" className="px-3 data-[state=on]:bg-primary/15 data-[state=on]:text-gold-ink">固定音色</ToggleGroupItem>
              </ToggleGroup>
              {(s.voice_source ?? "original") === "original" ? (
                s.voice_ref ? (
                  <>
                    <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground" title={s.voice_ref.text}>
                      参考原声：{shortClip(s.voice_ref.clip)} · {tsec(s.voice_ref.start)}–{tsec(s.voice_ref.end)} ·{" "}
                      <LangTag lang={s.voice_ref.lang === "zh" ? "zh" : "yue"} className="mx-0.5" /> {s.voice_ref.text}
                    </span>
                    <Button size="sm" variant="outline" onClick={() => {
                      if (audio.current && s.voice_ref) { audio.current.src = urls.voiceRefFile(batch, s.voice_ref); audio.current.play() }
                    }}><Play />试听原声</Button>
                    {refCands.length > 1 && (
                      <Button size="sm" variant="ghost" onClick={() => {
                        const i = refCands.findIndex((c) => c.clip === s.voice_ref?.clip && c.start === s.voice_ref?.start)
                        update((x) => ({ ...x, voice_ref: refCands[(i + 1) % refCands.length] }))
                        toast("已换一段原声做参考", { description: "保存后出片生效，配音缓存会按新声音重新生成" })
                      }}><Shuffle />换一段</Button>
                    )}
                  </>
                ) : <span className="text-xs text-muted-foreground">没找到合适的原声片段，会用固定音色</span>
              ) : (
                <span className="text-xs text-muted-foreground">不克隆老板声音，用固定种子生成的粤语声音</span>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* 时间线：拖动排序时色块跟着动 */}
      <div className="soft-shadow mt-4 flex h-9 overflow-hidden rounded-lg border bg-card">
        {keys.map((k, i) => {
          const l = s.lines[i]
          if (!l) return null
          return (
            <Tooltip key={k}>
              <TooltipTrigger asChild>
                <motion.button
                  layout
                  transition={{ type: "spring", stiffness: 500, damping: 40 }}
                  onClick={() => {
                    showSource(k)
                    document.getElementById(`line-${k}`)?.scrollIntoView({ behavior: "smooth", block: "center" })
                  }}
                  whileHover={{ y: -2 }}
                  className="relative h-full min-w-1 border-r border-card"
                  style={{ flex: Math.max(0.3, lineDuration(l)), background: `color-mix(in oklch, ${ROLE[l.role]?.color ?? ROLE.product.color} ${current === k ? 100 : 72}%, white)` }}
                >
                  {l.src_lang === "zh" && <span className="absolute inset-x-0 bottom-0 h-1 bg-zh" />}
                  {current === k && <motion.span layoutId="tl-current" className="absolute inset-0 ring-2 ring-foreground/70 ring-inset" />}
                </motion.button>
              </TooltipTrigger>
              <TooltipContent>{i + 1}. {l.subtitle}</TooltipContent>
            </Tooltip>
          )
        })}
      </div>
      <div className="mt-2 mb-5 flex flex-wrap items-center gap-4 text-xs text-muted-foreground">
        {(Object.keys(ROLE) as Role[]).map((r) => (
          <span key={r} className="flex items-center gap-1.5"><i className="size-2.5 rounded-sm" style={{ background: ROLE[r].color }} />{ROLE[r].label}</span>
        ))}
        <span className="flex items-center gap-1.5"><i className="h-1 w-3 rounded-sm bg-zh" />底部橙线：原话是普通话</span>
        <span className="ml-auto flex items-center gap-1.5"><Keyboard className="size-3.5" />↑↓ 选句 · Alt+↑↓ 调顺序 · 空格 看原片 · 拖 <GripVertical className="inline size-3" /> 排序</span>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[1fr_360px]">
        {/* 句子列表：可拖动排序 */}
        <div>
          <Reorder.Group axis="y" values={keys} onReorder={applyOrder} className="grid gap-2">
            <AnimatePresence initial={false}>
              {keys.map((k, i) =>
                s.lines[i] ? (
                  <LineRow
                    key={k}
                    k={k}
                    index={i}
                    line={s.lines[i]}
                    active={current === k}
                    ttsLoading={ttsLoading === k}
                    onSelect={() => setCurrent(k)}
                    onChange={(patch) => updateLine(i, patch)}
                    onSource={() => showSource(k)}
                    onTts={() => playTts(k)}
                    onMove={(d) => move(k, d)}
                    onRemove={() => remove(k)}
                  />
                ) : null,
              )}
            </AnimatePresence>
          </Reorder.Group>

          {/* 保存栏 */}
          <motion.div
            initial={{ y: 20, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2, duration: 0.4, ease }}
            className={cn(
              "sticky bottom-24 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-xl border bg-popover/90 px-3 py-2.5 lift-shadow backdrop-blur transition-colors",
              dirty && "border-warn/50",
            )}
          >
            <span className={cn("flex flex-1 items-center gap-2 text-xs", dirty ? "text-warn" : "text-muted-foreground")}>
              {dirty && <span className="ping-dot size-1.5 rounded-full bg-warn text-warn" />}
              {dirty ? "有未保存的修改" : savedAt ? `已保存 ${savedAt}` : "已保存"}
            </span>
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="ghost" size="sm" className="text-muted-foreground hover:text-destructive"><Trash2 />删除脚本</Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>删除这条剪辑脚本？</AlertDialogTitle>
                  <AlertDialogDescription>「{s.title}」会被删除，已经出的成片文件保留。</AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>取消</AlertDialogCancel>
                  <AlertDialogAction variant="destructive" onClick={del}>删除</AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            <Button variant="outline" onClick={() => save()}><Save />保存<kbd className="ml-1 text-[10px] text-muted-foreground">Ctrl+S</kbd></Button>
            <Button className="font-bold" onClick={renderNow} disabled={rendering} aria-busy={rendering}>
              {rendering ? <Loader2 className="animate-spin" /> : <Wand2 />}确认并出片
            </Button>
          </motion.div>
        </div>

        {/* 预览 */}
        <div className="grid gap-3 xl:sticky xl:top-16">
          <Phone>
            <AnimatePresence mode="wait">
              {preview.kind === "output" && s.has_output ? (
                <motion.video
                  key={`out-${outVer}`}
                  playsInline
                  preload="auto"
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25 }}
                  controls
                  autoPlay
                  className="size-full bg-black object-contain"
                  src={`${urls.output(batch, s.id)}?v=${outVer}`}
                />
              ) : pvLine ? (
                <motion.video
                  key={`src-${preview.kind === "source" ? preview.key : ""}`}
                  playsInline
                  preload="auto"
                  initial={{ opacity: 0, scale: 0.98 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.25 }}
                  controls
                  autoPlay
                  className="size-full bg-black object-contain"
                  src={urls.sourceClip(batch, pvLine)}
                />
              ) : (
                <motion.div key="empty" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="px-8 leading-relaxed">
                  <Video className="mx-auto mb-3 size-8 opacity-40" />
                  点句子右边的「原片」或时间线上的色块预览
                  <br />出片后这里播放成片
                </motion.div>
              )}
            </AnimatePresence>
          </Phone>
          <div className="min-h-5 text-xs text-muted-foreground">
            {pvLine && <>第 {pvIndex + 1} 句原片 · <LangTag lang={pvLine.src_lang} className="mx-1" />{pvLine.src_text}</>}
            {preview.kind === "output" && s.has_output && "成片"}
          </div>
          {s.has_output && (
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => setPreview({ kind: "output" })}><Film />看成片</Button>
              <Button size="sm" variant="outline" asChild><a href={urls.output(batch, s.id)} download><Download />下载 MP4</a></Button>
            </div>
          )}
        </div>
      </div>
      <audio ref={audio} className="hidden" />
    </div>
  )
}

interface RowProps {
  k: string
  index: number
  line: Line
  active: boolean
  ttsLoading: boolean
  onSelect: () => void
  onChange: (patch: Partial<Line>) => void
  onSource: () => void
  onTts: () => void
  onMove: (d: number) => void
  onRemove: () => void
}

function LineRow({ k, index, line: l, active, ttsLoading, onSelect, onChange, onSource, onTts, onMove, onRemove }: RowProps) {
  const controls = useDragControls()
  const long = subtitleTooLong(l.subtitle)
  return (
    <Reorder.Item
      value={k}
      id={`line-${k}`}
      dragListener={false}
      dragControls={controls}
      layout="position"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, height: 0, marginTop: -8, transition: { duration: 0.25 } }}
      whileDrag={{ scale: 1.015, boxShadow: "0 18px 40px oklch(0.25 0.02 260 / 18%)", zIndex: 20 }}
      transition={{ duration: 0.3, ease }}
      onClick={onSelect}
      className={cn(
        "soft-shadow grid grid-cols-[28px_1fr] gap-3 rounded-xl border border-l-[3px] bg-card p-3 transition-colors md:grid-cols-[28px_minmax(180px,0.85fr)_1.3fr_auto]",
        active && "border-primary/60 bg-accent ring-1 ring-primary/20",
      )}
      style={{ borderLeftColor: ROLE[l.role]?.color }}
    >
      <div className="flex flex-col items-center gap-1">
        <span className="grid size-7 place-items-center rounded-full bg-muted text-xs text-muted-foreground tabular">{index + 1}</span>
        <button
          aria-label="拖动排序"
          onPointerDown={(e) => controls.start(e)}
          className="cursor-grab touch-none rounded p-0.5 text-muted-foreground/60 transition-colors hover:bg-muted hover:text-foreground active:cursor-grabbing"
        >
          <GripVertical className="size-4" />
        </button>
      </div>
      <div className="min-w-0">
        <div className="text-[13px] leading-relaxed text-foreground/75"><LangTag lang={l.src_lang} className="mr-1.5 align-[1px]" />{l.src_text}</div>
        <div className="mt-1 text-[11px] text-muted-foreground tabular">{shortClip(l.clip)} · {tsec(l.start)}–{tsec(l.end)} · {lineDuration(l).toFixed(1)}s</div>
      </div>
      <div className="col-span-2 md:col-span-1">
        <Textarea
          value={l.subtitle}
          onChange={(e) => onChange({ subtitle: e.target.value })}
          onFocus={onSelect}
          rows={1}
          className="min-h-11 resize-y bg-background text-base font-semibold transition-shadow focus-visible:shadow-[0_0_0_4px_oklch(0.7_0.13_78/15%)]"
        />
        <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
          <span>粤语字幕 · 也是配音文案</span>
          <motion.span key={long ? "long" : "ok"} initial={{ opacity: 0.4 }} animate={{ opacity: 1 }} className={cn(long && "font-medium text-warn")}>
            {subtitleChars(l.subtitle)} 字{long && " · 单段太长，建议加逗号"}
          </motion.span>
        </div>
      </div>
      <div className="col-span-2 flex flex-wrap items-start justify-end gap-1.5 md:col-span-1 md:grid md:justify-items-end">
        <div className="flex gap-1.5">
          <Select value={l.role} onValueChange={(v) => onChange({ role: v as Role })}>
            <SelectTrigger size="sm" className="w-[76px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {(Object.keys(ROLE) as Role[]).map((r) => (
                <SelectItem key={r} value={r}>
                  <i className="size-2 rounded-full" style={{ background: ROLE[r].color }} />{ROLE[r].label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={l.zoom == null ? "auto" : String(l.zoom)} onValueChange={(v) => onChange({ zoom: v === "auto" ? null : parseFloat(v) })}>
            <SelectTrigger size="sm" className="w-[96px]"><SelectValue /></SelectTrigger>
            <SelectContent>
              {ZOOMS.map((z) => <SelectItem key={z.v} value={z.v}>{z.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="flex gap-1">
          <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); onSource() }}><Video />原片</Button>
          <Button size="sm" variant="outline" onClick={(e) => { e.stopPropagation(); onTts() }} disabled={ttsLoading} aria-busy={ttsLoading}>
            {ttsLoading ? <Loader2 className="animate-spin" /> : <AudioLines />}配音
          </Button>
          <Button size="icon-sm" variant="ghost" title="上移（Alt+↑）" onClick={(e) => { e.stopPropagation(); onMove(-1) }}><ArrowUp /></Button>
          <Button size="icon-sm" variant="ghost" title="下移（Alt+↓）" onClick={(e) => { e.stopPropagation(); onMove(1) }}><ArrowDown /></Button>
          <Button size="icon-sm" variant="ghost" title="删除这句（可撤销）" className="hover:text-destructive" onClick={(e) => { e.stopPropagation(); onRemove() }}><X /></Button>
        </div>
      </div>
    </Reorder.Item>
  )
}
