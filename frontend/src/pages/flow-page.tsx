// 剪辑流程：六个步骤横向排列，点开步骤查看配置、切换模型。
import { useCallback, useEffect, useState } from "react"
import { ArrowRight, ChevronDown, CircleAlert, Cpu, FlaskConical, Loader2, PencilLine, RefreshCw, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { ease } from "@/components/motion"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { api, type Pipeline, type PipelineField, type PipelineStep } from "@/lib/api"
import { cn } from "@/lib/utils"

const msg = (e: unknown) => String(e).replace(/^Error: /, "")

/** 折叠时步骤卡片上显示的模型小标签 */
function chips(step: PipelineStep): string[] {
  const out: string[] = []
  for (const f of step.fields) {
    if (f.type === "info") out.push(String(f.value))
    else if (f.type === "select") out.push(f.options.find((o) => o.value === f.value)?.label ?? String(f.value))
    else if (f.type === "list" && Array.isArray(f.value) && f.value.length) out.push(`备用 ${f.value.length} 个`)
  }
  return out.slice(0, 3)
}

function OptionSelect({ value, options, disabled, placeholder, onChange, className }: {
  value: string; options: PipelineField["options"]; disabled?: boolean; placeholder?: string; onChange: (v: string) => void; className?: string
}) {
  const cur = options.find((o) => o.value === value)
  return (
    <Select value={value} onValueChange={onChange} disabled={disabled}>
      <SelectTrigger className={cn("w-full rounded-lg", className)}>
        <SelectValue placeholder={placeholder}>{cur?.label ?? value}</SelectValue>
      </SelectTrigger>
      <SelectContent className="max-h-80">
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value} disabled={o.disabled}>
            <span>{o.label}</span>
            {o.note && <span className="text-xs text-muted-foreground">· {o.note}</span>}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function FieldEditor({ f, busy, onSave, onRefreshModels }: {
  f: PipelineField
  busy: boolean
  onSave: (v: unknown) => void
  onRefreshModels: () => Promise<void>
}) {
  const [custom, setCustom] = useState(false)
  const [text, setText] = useState(typeof f.value === "string" ? f.value : "")
  const [testing, setTesting] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  useEffect(() => setText(typeof f.value === "string" ? f.value : ""), [f.value])

  async function test() {
    setTesting(true)
    try {
      const r = await api.testLlm(String(f.value))
      toast.success(`${r.model} 能用`, { description: `回复「${r.reply}」，用了 ${r.seconds} 秒` })
    } catch (e) {
      toast.error("测试失败", { description: msg(e) })
    } finally {
      setTesting(false)
    }
  }

  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>{f.label}</span>
        {f.key === "llm.model" && (
          <span className="flex gap-1">
            <Button size="xs" variant="ghost" className="rounded-full" disabled={testing} onClick={test} title="发一句很短的话，看这个模型能不能用">
              {testing ? <Loader2 className="animate-spin" /> : <FlaskConical />}测试
            </Button>
            <Button size="xs" variant="ghost" className="rounded-full" disabled={refreshing}
              onClick={async () => { setRefreshing(true); await onRefreshModels(); setRefreshing(false) }} title="重新向中转站要一次模型列表">
              {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}刷新列表
            </Button>
          </span>
        )}
      </div>

      {f.type === "info" && <div className="text-sm font-medium">{String(f.value)}</div>}

      {f.type === "select" && (
        custom ? (
          <div className="flex gap-2">
            <Input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="模型名，例如 gpt-6"
              onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) { onSave(text.trim()); setCustom(false) } if (e.key === "Escape") setCustom(false) }}
              className="rounded-lg font-mono text-xs" />
            <Button size="sm" className="rounded-lg" disabled={busy || !text.trim()} onClick={() => { onSave(text.trim()); setCustom(false) }}>保存</Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <OptionSelect value={String(f.value)} options={f.options} disabled={busy} onChange={(v) => v !== f.value && onSave(v)} />
            {f.custom && (
              <Button size="icon-sm" variant="ghost" className="shrink-0 rounded-lg" title="列表里没有？自己填模型名" onClick={() => setCustom(true)}><PencilLine /></Button>
            )}
          </div>
        )
      )}

      {f.type === "list" && Array.isArray(f.value) && (
        <div className="grid gap-2">
          <div className="flex flex-wrap gap-1.5">
            {f.value.map((m, i) => (
              <span key={m} className="inline-flex items-center gap-1 rounded-full border py-0.5 pr-1 pl-2.5 text-xs">
                <span className="text-muted-foreground tabular">{i + 1}</span>{m}
                <button disabled={busy} title="去掉" onClick={() => onSave((f.value as string[]).filter((x) => x !== m))}
                  className="grid size-4 place-items-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"><X className="size-3" /></button>
              </span>
            ))}
            {!f.value.length && <span className="text-xs text-muted-foreground">没有备用模型</span>}
          </div>
          <OptionSelect
            value=""
            placeholder="添加备用模型…"
            options={f.options.filter((o) => !(f.value as string[]).includes(o.value))}
            disabled={busy}
            onChange={(v) => v && onSave([...(f.value as string[]), v])}
            className="h-8 text-xs"
          />
        </div>
      )}

      {f.type === "text" && (
        <Input value={text} disabled={busy} onChange={(e) => setText(e.target.value)}
          onBlur={() => text.trim() && text !== f.value && onSave(text.trim())}
          onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
          className="rounded-lg font-mono text-xs" />
      )}

      {f.type === "toggle" && (
        <button role="switch" aria-checked={!!f.value} disabled={busy} onClick={() => onSave(!f.value)}
          className="flex items-center gap-2.5 text-left text-sm">
          <span className={cn("relative h-5 w-9 shrink-0 rounded-full transition-colors", f.value ? "bg-foreground" : "bg-muted-foreground/30")}>
            <motion.span layout transition={{ type: "spring", stiffness: 500, damping: 32 }}
              className={cn("absolute top-0.5 size-4 rounded-full bg-background shadow", f.value ? "right-0.5" : "left-0.5")} />
          </span>
          {f.value ? "开" : "关"}
        </button>
      )}

      {f.note && <p className="text-[11px] leading-relaxed text-muted-foreground">{f.note}</p>}
    </div>
  )
}

function StepCard({ id, index, step, open, onToggle }: {
  id: string
  index: number
  step: PipelineStep
  open: boolean
  onToggle: () => void
}) {
  const editable = step.fields.some((f) => f.key)
  return (
    <button
      id={`flow-step-${id}`}
      aria-expanded={open}
      aria-controls={open ? "flow-step-details" : undefined}
      onClick={onToggle}
      className={cn("h-full min-h-40 w-full rounded-xl border bg-background p-3.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", open ? "border-foreground shadow-[0_8px_30px_oklch(0_0_0/7%)]" : "hover:border-foreground/40")}
    >
      <span className="flex items-center justify-between gap-2">
        <span className={cn("grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-medium tabular", open ? "bg-foreground text-background" : "bg-muted text-muted-foreground")}>
          {index + 1}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
          {editable && !open && "换模型"}
          <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}><ChevronDown className="size-4" /></motion.span>
        </span>
      </span>
      <span className="mt-3 block text-sm font-semibold">{step.title}</span>
      <span className="mt-2 flex flex-wrap gap-1">
        {chips(step).map((c, i) => (
          <span key={i} title={c} className={cn("inline-flex min-w-0 max-w-full items-center gap-1 rounded-full px-2 py-0.5 text-[11px]", i === 0 ? "bg-foreground/[0.07] font-medium text-foreground" : "bg-muted text-muted-foreground")}>
            {i === 0 && <Cpu className="size-3 shrink-0" />}<span className="truncate">{c}</span>
          </span>
        ))}
      </span>
    </button>
  )
}

export function FlowPage() {
  const [p, setP] = useState<Pipeline | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  const load = useCallback(() => api.pipeline().then((x) => { setP(x); setError(null) }).catch((e) => setError(msg(e))), [])
  useEffect(() => { load() }, [load])

  async function save(f: PipelineField, v: unknown) {
    if (!f.key) return
    setBusyKey(f.key)
    try {
      const r = await api.savePipeline({ [f.key]: v })
      setP(r.pipeline)
      const shown = f.type === "select" ? f.options.find((o) => o.value === v)?.label ?? String(v)
        : f.type === "toggle" ? (v ? "开" : "关")
        : Array.isArray(v) ? (v.join("、") || "无") : String(v)
      toast.success(`已保存：${f.label} → ${shown}`, { description: "下一次生成开始生效" })
    } catch (e) {
      toast.error("没有保存", { description: msg(e) })
    } finally {
      setBusyKey(null)
    }
  }
  async function refreshModels() {
    try {
      const r = await api.refreshLlmModels()
      if (r.error) toast.error("拿不到模型列表", { description: r.error })
      else toast.success(`中转站有 ${r.models.length} 个模型`)
      await load()
    } catch (e) {
      toast.error("刷新失败", { description: msg(e) })
    }
  }

  const steps = p?.branches.find((b) => b.id === "clip")?.steps.filter((s) => s.id !== "tts") ?? []
  const selected = steps.find((s) => s.id === open)

  if (error) {
    return (
      <div className="mx-auto grid max-w-md place-items-center px-6 pt-32 text-center">
        <CircleAlert className="size-6 text-muted-foreground" />
        <div className="mt-3 font-semibold">读不到流程配置</div>
        <p className="mt-1 text-sm text-muted-foreground">{error}。工作台刚更新过的话，要关掉重新打开（start.bat）才有这个功能。</p>
        <Button variant="outline" className="mt-4 rounded-full" onClick={load}>重试</Button>
      </div>
    )
  }
  if (!p) return <div className="grid min-h-svh place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>

  return (
    <div className="mx-auto max-w-7xl px-6 pt-10 pb-40">
      <span className="text-xs text-muted-foreground">流程图</span>
      <h1 className="mt-3 text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl">剪辑流程</h1>
      <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted-foreground">
        从上传素材到出片，点开步骤查看配置或切换模型。修改在下一次生成时生效，识别模型需在没有任务运行时更换。
      </p>
      {!p.llm_ready && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-destructive"><CircleAlert className="size-4" />还没有填大模型 API Key（secrets.yaml），出脚本会失败</p>
      )}

      <div role="region" aria-label="剪辑流程，可横向滚动" tabIndex={0} className="scrollbar-thin mt-10 overflow-x-auto rounded-xl pb-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <ol className="flex min-w-[1120px] items-stretch gap-8 py-2">
          {steps.map((s, i) => (
            <li key={s.id} className="relative min-w-0 flex-1">
              <StepCard id={s.id} index={i} step={s} open={open === s.id}
                onToggle={() => setOpen((o) => (o === s.id ? null : s.id))} />
              {i < steps.length - 1 && <ArrowRight aria-hidden="true" className="absolute top-20 -right-6 size-4 -translate-y-1/2 text-muted-foreground/50" />}
            </li>
          ))}
        </ol>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        {selected && (
          <motion.section key={selected.id} id="flow-step-details" aria-labelledby={`flow-step-${selected.id}`}
            initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease }} className="max-w-2xl overflow-hidden">
            <div className="mt-4 rounded-xl border bg-background p-5">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">{selected.title}</h2>
                <Button size="icon-sm" variant="ghost" aria-label={`收起${selected.title}配置`} onClick={() => setOpen(null)}><X /></Button>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{selected.desc}</p>
              <div className="mt-5 grid gap-4">
                {selected.fields.map((f, i) => (
                  <FieldEditor key={`${f.key ?? "info"}-${i}`} f={f} busy={busyKey === f.key && !!busyKey}
                    onSave={(v) => save(f, v)} onRefreshModels={refreshModels} />
                ))}
              </div>
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </div>
  )
}
