import type { Line, Role, Script } from "./api"

export const mmss = (t: number) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`
export const tsec = (t: number) => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`
export const minutes = (s: number) => (s / 60).toFixed(1)

/** 2025_09_23_10_33_30_IMG_5818.MOV → IMG_5818 */
export const shortClip = (c: string) => c.replace(/^\d{4}_\d\d_\d\d_[\d_]+_/, "").replace(/\.\w+$/, "")

export const ROLE: Record<Role, { label: string; color: string }> = {
  hook: { label: "开头", color: "var(--hook)" },
  product: { label: "讲解", color: "var(--product)" },
  cta: { label: "结尾", color: "var(--cta)" },
}

export const STATUS = {
  draft: { label: "待审核", className: "bg-muted text-foreground/75 border-border" },
  approved: { label: "已确认", className: "bg-primary/15 text-gold-ink border-primary/45" },
  rendered: { label: "已出片", className: "bg-ok/12 text-ok border-ok/40" },
} as const

export const lineDuration = (l: Line) => l.end - l.start
export const scriptDuration = (s: Script) => s.lines.reduce((a, l) => a + lineDuration(l), 0)

export const subtitleChars = (t: string) => t.replace(/[，,。.！!？?、\s]/g, "").length
/** 逗号之间的一段超过 16 个字（两行）就提醒 */
export const subtitleTooLong = (t: string) => t.split(/[，,、；;]/).some((p) => p.trim().length > 16)
