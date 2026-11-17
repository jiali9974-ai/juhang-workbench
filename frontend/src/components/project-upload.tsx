import { useRef, useState } from "react"
import { FileVideo, FolderUp, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { UploadList, useUploadQueue } from "@/components/upload-queue"
import { Button } from "@/components/ui/button"
import { api } from "@/lib/api"
import { todayName } from "@/lib/current"
import { filesFromDrop, folderOf, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"

const message = (error: unknown) => String(error).replace(/^Error: /, "")

/** 每次选择或拖入一批素材都会建立独立项目，上传过程中留在项目列表。 */
export function ProjectUpload({ onCreated, onUploaded }: {
  onCreated: (batch: string) => void
  onUploaded: () => void
}) {
  const [creating, setCreating] = useSessionState("project-upload.creating", false)
  const [over, setOver] = useState(false)
  const creatingRef = useRef(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const queue = useUploadQueue("", onUploaded, "project-create")
  const locked = creating || queue.busy

  async function addFiles(files: File[], folder: string | null) {
    if (creating || creatingRef.current || queue.busy) return toast("请等当前素材上传完成")
    const videos = files.filter(isVideo)
    if (!videos.length) return toast.error("没有找到视频")
    creatingRef.current = true
    setCreating(true)
    try {
      const hint = folder || (videos.length === 1 ? videos[0].name.replace(/\.[^.]+$/, "") : todayName())
      let created: string | null = null
      for (let index = 1; index <= 50; index++) {
        try {
          const result = await api.createBatch(index === 1 ? hint : `${hint}_${index}`)
          created = result.batch
          break
        } catch (error) {
          if (!message(error).includes("已经有叫")) throw error
        }
      }
      if (!created) throw new Error("同名项目太多，请换一个文件夹名")
      queue.clearDone()
      queue.add(videos, created)
      onCreated(created)
    } catch (error) {
      toast.error("创建项目失败", { description: message(error) })
    } finally {
      creatingRef.current = false
      setCreating(false)
    }
  }

  return (
    <div>
      <div role="button" tabIndex={locked ? -1 : 0} aria-label="上传素材创建项目" aria-disabled={locked}
        onClick={() => { if (!locked) fileRef.current?.click() }}
        onKeyDown={(event) => {
          if (!locked && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault()
            fileRef.current?.click()
          }
        }}
        onDragOver={(event) => { event.preventDefault(); if (!locked) setOver(true) }}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false) }}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          filesFromDrop(event.dataTransfer).then(({ files, folder }) => addFiles(files, folder))
            .catch((error) => toast.error("读取素材失败", { description: message(error) }))
        }}
        className={cn("flex min-h-48 flex-col items-center justify-center rounded-2xl border-2 border-dashed px-5 py-8 text-center transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring", locked ? "cursor-wait bg-muted/40" : "cursor-pointer bg-muted/20 hover:border-foreground/30 hover:bg-muted/40", over && "border-foreground bg-muted/60")}>
        <div className="flex items-center gap-2 text-base font-semibold">
          {creating && <Loader2 className="size-4 animate-spin" />}
          {creating ? "正在创建项目" : queue.busy ? "正在上传素材" : over ? "松开创建项目" : "拖入素材，创建项目"}
        </div>
        <div className="mt-5 flex flex-wrap justify-center gap-2" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
          <Button variant="outline" className="rounded-full bg-background" disabled={locked} onClick={() => fileRef.current?.click()}><FileVideo />选择视频</Button>
          <Button variant="outline" className="rounded-full bg-background" disabled={locked} onClick={() => folderRef.current?.click()}><FolderUp />选择文件夹</Button>
        </div>
      </div>
      <input ref={fileRef} type="file" multiple accept={VIDEO_ACCEPT} className="hidden"
        onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) addFiles(files, null) }} />
      <input ref={(element) => {
        folderRef.current = element
        element?.setAttribute("webkitdirectory", "")
        element?.setAttribute("directory", "")
      }} type="file" multiple className="hidden"
        onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) addFiles(files, folderOf(files)) }} />
      <UploadList items={queue.items} onCancel={queue.cancel} onClear={queue.clearDone} maxVisibleItems={3} />
    </div>
  )
}
