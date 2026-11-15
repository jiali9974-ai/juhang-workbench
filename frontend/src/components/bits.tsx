// 小组件：语种标签、状态徽章、语种比例条、手机预览框
import type { ReactNode } from "react"

import { Badge } from "@/components/ui/badge"
import type { ScriptStatus } from "@/lib/api"
import { STATUS } from "@/lib/format"
import { cn } from "@/lib/utils"

export function LangTag({ lang, className }: { lang: string; className?: string }) {
  const map: Record<string, [string, string]> = {
    yue: ["粤", "bg-yue/15 text-yue"],
    zh: ["普", "bg-zh/15 text-zh"],
  }
  const [label, cls] = map[lang] ?? [lang, "bg-muted text-muted-foreground"]
  return (
    <span className={cn("inline-flex h-[18px] items-center rounded px-1.5 text-[11px] font-bold leading-none", cls, className)}>
      {label}
    </span>
  )
}

export function StatusBadge({ status, className }: { status: ScriptStatus; className?: string }) {
  const s = STATUS[status] ?? STATUS.draft
  return (
    <Badge variant="outline" className={cn("rounded-full", s.className, className)}>
      {s.label}
    </Badge>
  )
}

export function LangBar({ yue, zh, other = 0, className }: { yue: number; zh: number; other?: number; className?: string }) {
  const total = yue + zh + other || 1
  return (
    <div className={cn("flex h-2 overflow-hidden rounded-full bg-muted", className)}>
      <span className="h-full bg-yue transition-all" style={{ width: `${(yue / total) * 100}%` }} />
      <span className="h-full bg-zh transition-all" style={{ width: `${(zh / total) * 100}%` }} />
      <span className="h-full bg-foreground/15 transition-all" style={{ width: `${(other / total) * 100}%` }} />
    </div>
  )
}

export function Phone({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-[30px] border bg-card p-2.5 lift-shadow ring-1 ring-foreground/5", className)}>
      <div className="grid aspect-[9/16] place-items-center overflow-hidden rounded-[22px] bg-gradient-to-b from-muted to-secondary text-center text-sm text-muted-foreground">
        {children}
      </div>
    </div>
  )
}
