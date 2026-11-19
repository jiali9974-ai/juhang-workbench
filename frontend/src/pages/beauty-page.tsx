import { useCallback, useEffect, useMemo, useState } from "react"
import { Loader2, RefreshCw } from "lucide-react"
import { toast } from "sonner"

import { FrameEditor } from "@/components/frame-editor"
import { Button } from "@/components/ui/button"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { useSessionState } from "@/hooks/use-session-state"
import { api, type Batch, type OutputVideo } from "@/lib/api"
import { getCurrent } from "@/lib/current"
import { PAGE_CONTAINER, PAGE_TITLE } from "@/lib/layout"

const sourceKey = (video: OutputVideo) => JSON.stringify([video.batch, video.id])

export function BeautyPage({ batch }: { batch?: string }) {
  const [outputs, setOutputs] = useSessionState<OutputVideo[]>("beauty.outputs", [])
  const [batches, setBatches] = useSessionState<Batch[]>("beauty.batches", [])
  const [selection, setSelection] = useSessionState("beauty.source", "default")
  const [revision, setRevision] = useSessionState("beauty.sources-revision", 0)
  const [refreshing, setRefreshing] = useState(true)

  const refresh = useCallback((notify = false) =>
    Promise.all([api.outputs(), api.batches()]).then(([videos, projects]) => {
      setOutputs(videos)
      setBatches(projects)
      setSelection((current) => current === "default" || videos.some((video) => sourceKey(video) === current) ? current : "default")
      if (notify) {
        setRevision((value) => value + 1)
        toast.success("成片列表已更新")
      }
    }).catch((error: unknown) => {
      toast.error("更新成片失败", { description: String(error).replace(/^Error: /, "") })
    }).finally(() => setRefreshing(false)), [setOutputs, setBatches, setSelection, setRevision])

  useEffect(() => { void refresh() }, [refresh])

  const selected = outputs.find((video) => sourceKey(video) === selection)
  const source = useMemo(() => selected ? { batch: selected.batch, id: selected.id } : null, [selected])
  const project = batches.find((item) => item.batch === (selected?.batch || batch || getCurrent()))

  const header = (
    <div className="mb-8">
      <h1 className={PAGE_TITLE}>画面编辑</h1>
      <p className="mt-3 text-sm text-muted-foreground">调整画面质感、编辑文字，让重点动起来。</p>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <Select value={selected ? sourceKey(selected) : "default"} onValueChange={setSelection}>
          <SelectTrigger className="w-64 max-w-full rounded-full" aria-label="预览画面来源"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="default">默认测试图</SelectItem>
            {outputs.map((video) => <SelectItem key={sourceKey(video)} value={sourceKey(video)}>
              {video.title}{video.title !== video.id && ` · ${video.id}`}
            </SelectItem>)}
          </SelectContent>
        </Select>
        <Button variant="outline" className="rounded-full" disabled={refreshing} aria-busy={refreshing}
          onClick={() => { setRefreshing(true); void refresh(true) }}>
          {refreshing ? <Loader2 className="animate-spin" /> : <RefreshCw />}更新成片
        </Button>
      </div>
    </div>
  )

  return (
    <div className={PAGE_CONTAINER}>
      <FrameEditor batch={project?.batch ?? null} scripts={project?.scripts ?? 0} source={source}
        revision={`${selected?.updated ?? "default"}:${revision}`} header={header} />
    </div>
  )
}
