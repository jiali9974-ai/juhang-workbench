// 美颜设置页：左边说明和强度，右边用项目素材里的画面实时对比。
import { useEffect, useState } from "react"
import { Loader2 } from "lucide-react"

import { BeautyEditor } from "@/components/beauty-panel"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { go } from "@/hooks/use-route"
import { api, type Batch } from "@/lib/api"
import { getCurrent } from "@/lib/current"

export function BeautyPage({ batch }: { batch?: string }) {
  const [list, setList] = useState<Batch[] | null>(null)
  useEffect(() => { api.batches().then(setList).catch(() => setList([])) }, [])

  if (!list) return <div className="grid min-h-svh place-items-center"><Loader2 className="size-6 animate-spin text-muted-foreground" /></div>

  const usable = list.filter((b) => b.clips > 0)
  const cur = getCurrent()
  const chosen =
    usable.find((b) => b.batch === batch) ??
    usable.find((b) => b.batch === cur) ??
    usable[0] ??
    null

  const header = (
    <div className="mb-8">
      <span className="text-xs text-muted-foreground">美颜设置</span>
      <h1 className="mt-3 text-4xl font-bold tracking-tight md:text-5xl lg:text-6xl">美颜</h1>
      <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
        调好强度、对比满意后保存，之后出的成片都按这个设置。有人脸的画面才磨皮，手表特写只锐化，不磨。
      </p>
      {usable.length > 0 && chosen && (
        <div className="mt-5 flex items-center gap-3 text-sm">
          <span className="text-muted-foreground">用哪个项目的画面预览</span>
          <Select value={chosen.batch} onValueChange={(v) => go({ page: "beauty", batch: v })}>
            <SelectTrigger className="w-48 rounded-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              {usable.map((b) => <SelectItem key={b.batch} value={b.batch}>{b.batch}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  )

  return (
    <div className="mx-auto max-w-6xl px-6 pt-10 pb-40">
      <BeautyEditor batch={chosen?.batch ?? null} scripts={chosen?.scripts ?? 0} header={header} />
    </div>
  )
}
