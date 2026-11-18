import { useRef, useState } from "react"
import { FileVideo, FolderUp, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { useUploadQueue } from "@/components/upload-queue"
import { UploadGroups } from "@/components/upload-groups"
import { Button } from "@/components/ui/button"
import { createUploadProject } from "@/lib/upload-projects"
import { filesFromDrop, folderOf, isVideo, VIDEO_ACCEPT } from "@/lib/upload"
import { cn } from "@/lib/utils"
import { useSessionState } from "@/hooks/use-session-state"

const message = (error: unknown) => String(error).replace(/^Error: /, "")

/** 每次选择或拖入一批素材都会建立独立项目，上传过程中留在项目列表。 */
export function ProjectUpload({ onCreated, onUploaded }: {
  onCreated: (batch: string) => void
  onUploaded: () => void
}) {
  const [creating, setCreating] = useSessionState("project-upload.pending", 0)
  const [over, setOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const queue = useUploadQueue("", onUploaded, "project-create")

  async function addFiles(files: File[], folder: string | null) {
    const videos = files.filter(isVideo)
    if (!videos.length) return toast.error("没有找到视频")
    setCreating((count) => count + 1)
    try {
      const created = await createUploadProject(files, folder)
      queue.add(videos, created)
      onCreated(created)
    } catch (error) {
      toast.error("创建项目失败", { description: message(error) })
    } finally {
      setCreating((count) => count - 1)
    }
  }

  return (
    <div>
      <div role="button" tabIndex={0} aria-label="上传素材创建项目"
        onClick={() => fileRef.current?.click()}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault()
            fileRef.current?.click()
          }
        }}
        onDragOver={(event) => { event.preventDefault(); setOver(true) }}
        onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setOver(false) }}
        onDrop={(event) => {
          event.preventDefault()
          setOver(false)
          filesFromDrop(event.dataTransfer).then((groups) => Promise.all(groups.map(({ files, folder }) => addFiles(files, folder))))
            .catch((error) => toast.error("读取素材失败", { description: message(error) }))
        }}
        className={cn("flex min-h-48 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed bg-muted/20 px-5 py-8 text-center transition-colors outline-none hover:border-foreground/30 hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring", over && "border-foreground bg-muted/60")}>
        <div className="flex items-center gap-2 text-base font-semibold">
          {creating > 0 && <Loader2 className="size-4 animate-spin" />}
          {over ? "松开创建新素材项目" : creating ? "正在创建项目，可继续添加" : "拖入素材，创建项目"}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">每个文件夹独立一个项目，再次上传会创建新项目</p>
        <div className="mt-5 flex flex-wrap justify-center gap-2" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
          <Button variant="outline" className="rounded-full bg-background" onClick={() => fileRef.current?.click()}><FileVideo />选择视频</Button>
          <Button variant="outline" className="rounded-full bg-background" onClick={() => folderRef.current?.click()}><FolderUp />选择文件夹</Button>
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
      <UploadGroups items={queue.items} maxVisibleItems={3} />
    </div>
  )
}
