import { Loader2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { subtitleChanges, type SubtitleDraft } from "@/lib/frame-workflow"
import { tsec } from "@/lib/format"

export function SubtitleContent({ draft, loading, error, disabled, selected, onSelect, onChange, onReload }: {
  draft?: SubtitleDraft; loading: boolean; error: string; disabled: boolean; selected: number
  onSelect: (index: number) => void; onChange: (index: number, value: string) => void; onReload: () => void
}) {
  return <section className="grid gap-3 rounded-2xl border p-5" aria-label="口播字幕内容">
    <div className="flex items-center justify-between gap-3"><h3 className="font-semibold">口播字幕内容</h3>
      {draft && <Button size="sm" variant="ghost" disabled={disabled || loading} onClick={onReload}><RefreshCw />重新载入</Button>}</div>
    <p className="text-xs leading-relaxed text-muted-foreground">修改所选成片逐句显示的字幕，保留原声和剪辑时间。点选一句可在右侧预览。</p>
    {loading ? <div className="flex gap-2 text-sm text-muted-foreground"><Loader2 className="size-4 animate-spin" />读取成片字幕</div> : error ?
      <div role="alert" className="grid gap-2 text-sm text-destructive">{error}<Button size="sm" variant="outline" onClick={onReload}>重试</Button></div> : draft ? <>
        <div className="grid max-h-[30rem] gap-3 overflow-auto pr-1">
          {draft.script.lines.map((line, index) => <label key={`${index}:${line.clip}:${line.start}`} className={`grid gap-1.5 rounded-lg p-2 text-xs ${index === selected ? "bg-muted" : ""}`}>
            <span className="text-muted-foreground">第 {index + 1} 句 · 素材 {tsec(line.start)}–{tsec(line.end)}</span>
            <textarea aria-label={`第${index + 1}句口播字幕`} rows={2} maxLength={2000} disabled={disabled} value={line.subtitle}
              className="w-full resize-y rounded-lg border bg-background p-2 text-sm text-foreground outline-none focus:border-foreground/50"
              onFocus={() => onSelect(index)} onChange={(event) => onChange(index, event.target.value)} />
          </label>)}
        </div>
        <p className="text-xs text-muted-foreground">{subtitleChanges(draft).length ? `${subtitleChanges(draft).length} 句字幕待保存` : `${draft.script.lines.length} 句字幕 · 已保存`}</p>
      </> : <p className="text-sm text-muted-foreground">先在上方选择一条成片，即可编辑它的口播字幕。</p>}
  </section>
}
