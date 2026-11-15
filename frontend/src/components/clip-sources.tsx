import { useRef, useState } from "react"
import { FolderInput, FolderUp, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { DropZone, UploadList, useUploadQueue } from "@/components/upload-queue"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useJobs } from "@/hooks/use-jobs"
import { api } from "@/lib/api"

type Queue = ReturnType<typeof useUploadQueue>

/** 素材剪辑项目的「添加素材」：拖入/点选视频、选择文件夹上传、本机文件夹路径一键加载 */
export function ClipSources({ batch, queue, big, onChanged }: { batch: string; queue: Queue; big?: boolean; onChanged: () => void }) {
  const { watch } = useJobs()
  const folderRef = useRef<HTMLInputElement | null>(null)
  const [path, setPath] = useState("")
  const [importing, setImporting] = useState(false)

  async function importPath() {
    const p = path.trim()
    if (!p) return toast.error("请填写本机文件夹路径")
    setImporting(true)
    try {
      const j = await api.importFolder(batch, p)
      toast("正在加载文件夹里的视频", { description: p })
      watch(j, (job) => {
        setImporting(false)
        const r = job.result as { added: number; linked: number; copied: number; total: number }
        toast.success(`已加载 ${r.added} 个视频${r.total > r.added ? `（${r.total - r.added} 个之前已加过）` : ""}`,
          { description: r.linked ? `${r.linked} 个用硬链接，没有占用额外硬盘空间` : r.copied ? `${r.copied} 个是复制过来的` : undefined })
        setPath("")
        onChanged()
      })
    } catch (e) {
      setImporting(false)
      toast.error("加载失败", { description: String(e).replace(/^Error: /, "") })
    }
  }

  return (
    <div id="clip-sources">
      <DropZone onFiles={queue.add} big={big} batch={batch} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button variant="outline" onClick={() => folderRef.current?.click()}><FolderUp />选择文件夹上传</Button>
        <input
          ref={(el) => {
            folderRef.current = el
            el?.setAttribute("webkitdirectory", "")   // 选择整个文件夹（含子文件夹）
            el?.setAttribute("directory", "")
          }}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => { if (e.target.files?.length) queue.add(e.target.files); e.target.value = "" }}
        />
        <span className="text-xs text-muted-foreground">或</span>
        <div className="flex min-w-[320px] flex-1 gap-2">
          <Input
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && importPath()}
            placeholder="填这台电脑上的文件夹路径，例如 D:\巨航\素材\素材\9.29"
            className="font-mono text-xs"
          />
          <Button onClick={importPath} disabled={importing} className="shrink-0">
            {importing ? <Loader2 className="animate-spin" /> : <FolderInput />}一键加载文件夹
          </Button>
        </div>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">本机路径加载：同一块硬盘用硬链接，几十 GB 也是秒加、不占额外空间；子文件夹里的视频会一起加进来，重复的自动跳过。</p>
      <UploadList items={queue.items} onCancel={queue.cancel} onClear={queue.clearDone} />
    </div>
  )
}
