import { useEffect, useRef, useState } from "react"
import { Film, Loader2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { urls, type OutputVideo } from "@/lib/api"
import { outputKey } from "@/lib/frame-workflow"

export function ApplyToOutputs({ videos, preferred, busy, onClose, onApply }: {
  videos: OutputVideo[]; preferred: string | null; busy: boolean
  onClose: () => void; onApply: (keys: string[]) => Promise<string[]>
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [selected, setSelected] = useState<string[]>(() => preferred ? [preferred] : [])
  useEffect(() => { dialog.current?.showModal() }, [])
  const keys = selected.filter((key) => videos.some((video) => outputKey(video) === key))
  return <dialog ref={dialog} aria-labelledby="apply-outputs-title" aria-describedby="apply-outputs-help"
    onClose={onClose} onCancel={(event) => { if (busy) event.preventDefault() }}
    onClick={(event) => { if (event.target === event.currentTarget && !busy) onClose() }}
    className="fixed inset-0 m-auto max-h-[85svh] w-[calc(100%-2rem)] max-w-xl rounded-2xl border bg-background p-5 text-foreground shadow-xl backdrop:bg-black/60">
    <div className="flex items-center justify-between gap-3"><h2 id="apply-outputs-title" className="text-lg font-semibold">选择要应用的成片</h2>
      <Button variant="ghost" size="icon" disabled={busy} aria-label="关闭成片选择" onClick={onClose}><X /></Button></div>
    <p id="apply-outputs-help" className="mt-2 text-sm text-muted-foreground">保存当前画面设置及字幕修改，将勾选的成片逐条重新出片。</p>
    <div className="my-4 grid max-h-[48svh] gap-2 overflow-auto">
      {videos.length ? videos.map((video) => {
        const key = outputKey(video)
        return <label key={key} className="flex cursor-pointer items-center gap-3 rounded-xl border p-3 has-checked:border-foreground">
          <input type="checkbox" aria-label={`应用到${video.title} · ${video.batch} · ${video.id}`} disabled={busy} checked={keys.includes(key)}
            onChange={(event) => setSelected((current) => event.target.checked ? [...current, key] : current.filter((item) => item !== key))} />
          <img src={`${urls.outputThumb(video.batch, video.id)}?v=${video.updated}`} alt="" loading="lazy" className="h-16 w-10 rounded-md bg-muted object-cover" />
          <span className="min-w-0"><span className="block truncate text-sm font-medium">{video.title}</span><span className="text-xs text-muted-foreground">{video.batch} · {video.id}</span></span>
        </label>
      }) : <p className="py-6 text-center text-sm text-muted-foreground">还没有可以重新出片的成片。</p>}
    </div>
    <div className="flex items-center justify-end gap-2 border-t pt-4"><span className="mr-auto text-xs text-muted-foreground">已选 {keys.length} 条</span>
      <Button variant="outline" disabled={busy} onClick={onClose}>取消</Button>
      <Button disabled={busy || !keys.length} onClick={() => void onApply(keys).then((failed) => setSelected(failed))}>
        {busy ? <Loader2 className="animate-spin" /> : <Film />}应用并重新出片（{keys.length}）</Button></div>
  </dialog>
}
