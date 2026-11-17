// 流程图（思维导图）：工作台 → 两条流程 → 每一步，每一步上标着现在用的模型，点开直接改。
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, CircleAlert, Cpu, FlaskConical, Loader2, PencilLine, RefreshCw, X } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import { ease } from "@/components/motion"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useIsMobile } from "@/hooks/use-mobile"
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

function StepCard({ id, index, step, open, onToggle, busyKey, onSave, onRefreshModels, nodeRef, className }: {
  id: string
  className?: string
  index: number
  step: PipelineStep
  open: boolean
  onToggle: () => void
  busyKey: string | null
  onSave: (f: PipelineField, v: unknown) => void
  onRefreshModels: () => Promise<void>
  nodeRef: (el: HTMLElement | null) => void
}) {
  const editable = step.fields.some((f) => f.key)
  return (
    <div
      ref={nodeRef}
      data-node={id}
      className={cn("w-[400px] rounded-xl border bg-background transition-colors", className, open ? "border-foreground shadow-[0_8px_30px_oklch(0_0_0/7%)]" : "hover:border-foreground/40", step.off && !open && "opacity-55")}
    >
      <button onClick={onToggle} className="flex w-full items-start gap-3 px-3.5 py-3 text-left">
        <span className={cn("mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-[11px] font-medium tabular", open ? "bg-foreground text-background" : "bg-muted text-muted-foreground")}>
          {index + 1}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm font-semibold">
            {step.title}
            {step.off && <span className="rounded-full bg-muted px-1.5 py-px text-[10px] font-normal text-muted-foreground">已关闭</span>}
          </span>
          <span className="mt-1.5 flex flex-wrap gap-1">
            {chips(step).map((c, i) => (
              <span key={i} className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px]", i === 0 ? "bg-foreground/[0.07] font-medium text-foreground" : "bg-muted text-muted-foreground")}>
                {i === 0 && <Cpu className="size-3" />}{c}
              </span>
            ))}
          </span>
        </span>
        <span className="mt-0.5 flex shrink-0 items-center gap-1 text-[11px] text-muted-foreground">
          {editable && !open && "换模型"}
          <motion.span animate={{ rotate: open ? 180 : 0 }} transition={{ duration: 0.2 }}><ChevronDown className="size-4" /></motion.span>
        </span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease }}
            className="overflow-hidden"
          >
            <div className="grid gap-4 border-t px-3.5 pt-3 pb-4">
              <p className="text-xs leading-relaxed text-muted-foreground">{step.desc}</p>
              {step.fields.map((f, i) => (
                <FieldEditor key={`${f.key ?? "info"}-${i}`} f={f} busy={!!busyKey && busyKey === f.key} onSave={(v) => onSave(f, v)} onRefreshModels={onRefreshModels} />
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function FlowPage() {
  const mobile = useIsMobile()
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
      toast.success(`已保存：${f.label} → ${shown}`, { description: "写进了 config.yaml，下一次生成开始生效" })
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

  // ---- 连线：量出每个节点的位置，用曲线把父节点右边连到子节点左边 ----
  const box = useRef<HTMLDivElement>(null)
  const nodes = useRef(new Map<string, HTMLElement>())
  const refs = useRef(new Map<string, (el: HTMLElement | null) => void>())
  const nodeRef = (id: string) => {
    let r = refs.current.get(id)
    if (!r) {
      r = (el) => { if (el) nodes.current.set(id, el); else nodes.current.delete(id) }
      refs.current.set(id, r)
    }
    return r
  }
  const edges = useMemo(() => (p ? [
    ...p.branches.map((b) => ["root", b.id] as const),
    ...p.branches.flatMap((b) => b.steps.map((s) => [b.id, `${b.id}/${s.id}`] as const)),
  ] : []), [p])
  const [paths, setPaths] = useState<{ id: string; d: string; on: boolean }[]>([])
  const measure = useCallback(() => {
    const c = box.current
    if (!c) return
    const cr = c.getBoundingClientRect()
    const out: { id: string; d: string; on: boolean }[] = []
    for (const [a, b] of edges) {
      const ea = nodes.current.get(a)
      const eb = nodes.current.get(b)
      if (!ea || !eb) continue
      const ra = ea.getBoundingClientRect()
      const rb = eb.getBoundingClientRect()
      const x1 = ra.right - cr.left
      const y1 = ra.top + ra.height / 2 - cr.top
      const x2 = rb.left - cr.left
      const y2 = rb.top + Math.min(rb.height / 2, 30) - cr.top     // 展开的卡片连到标题那一行
      const mx = (x1 + x2) / 2
      out.push({ id: `${a}>${b}`, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, on: b === open || (a === "root" && !!open?.startsWith(`${b}/`)) })
    }
    setPaths(out)
  }, [edges, open])
  useLayoutEffect(() => {
    measure()
    const c = box.current
    if (!c) return
    const ro = new ResizeObserver(measure)
    ro.observe(c)
    nodes.current.forEach((el) => ro.observe(el))
    return () => ro.disconnect()
  }, [measure, mobile, p])

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
        从上传素材到出片的每一步，以及每一步用的模型。点开一步就能换模型，改完自动写进 config.yaml，下一次生成开始生效。
        识别模型和 Ming 模型要在没有任务在跑的时候换。
      </p>
      {!p.llm_ready && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-destructive"><CircleAlert className="size-4" />还没有填大模型 API Key（secrets.yaml），出脚本会失败</p>
      )}

      {mobile ? (
        <div className="mt-8 grid gap-8">
          {p.branches.map((b) => (
            <section key={b.id}>
              <div className="rounded-2xl border-2 border-foreground/80 px-4 py-3">
                <div className="font-semibold">{b.title}</div>
                <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{b.desc}</div>
              </div>
              <div className="mt-3 ml-5 grid gap-2.5 border-l-2 border-foreground/15 pl-4">
                {b.steps.map((s, i) => {
                  const id = `${b.id}/${s.id}`
                  return (
                    <StepCard key={id} id={id} index={i} step={s} className="w-full" open={open === id}
                      onToggle={() => setOpen((o) => (o === id ? null : id))} busyKey={busyKey} onSave={save}
                      onRefreshModels={refreshModels} nodeRef={() => {}} />
                  )
                })}
              </div>
            </section>
          ))}
        </div>
      ) : (
      <div className="scrollbar-thin mt-10 overflow-x-auto pb-4">
        <div ref={box} className="relative mx-auto flex w-max items-center gap-16 py-2 pr-2">
          <svg className="pointer-events-none absolute inset-0 size-full overflow-visible" aria-hidden>
            {paths.map((x) => (
              <path key={x.id} d={x.d} fill="none" strokeWidth={x.on ? 2 : 1.5}
                className={cn("transition-[stroke] duration-200", x.on ? "stroke-foreground" : "stroke-foreground/15")} />
            ))}
          </svg>

          {/* 根 */}
          <div ref={nodeRef("root")} className="relative rounded-2xl bg-foreground px-5 py-4 text-background shadow-lg">
            <div className="text-[11px] opacity-60">JUHANG STUDIO</div>
            <div className="mt-0.5 font-semibold whitespace-nowrap">{p.root}</div>
          </div>

          {/* 两条流程 */}
          <div className="relative flex flex-col gap-12">
            {p.branches.map((b) => (
              <div key={b.id} className="flex items-center gap-16">
                <div ref={nodeRef(b.id)} className="w-44 rounded-2xl border-2 border-foreground/80 bg-background px-4 py-3">
                  <div className="font-semibold">{b.title}</div>
                  <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{b.desc}</div>
                </div>
                <div className="flex flex-col gap-2.5">
                  {b.steps.map((s, i) => {
                    const id = `${b.id}/${s.id}`
                    return (
                      <StepCard
                        key={id}
                        id={id}
                        index={i}
                        step={s}
                        open={open === id}
                        onToggle={() => setOpen((o) => (o === id ? null : id))}
                        busyKey={busyKey}
                        onSave={save}
                        onRefreshModels={refreshModels}
                        nodeRef={nodeRef(id)}
                      />
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      )}
    </div>
  )
}
