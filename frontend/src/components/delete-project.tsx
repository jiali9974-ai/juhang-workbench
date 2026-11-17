import { useState } from "react"
import { ArrowLeft, FolderX, Loader2, Trash2 } from "lucide-react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Button } from "@/components/ui/button"
import { go } from "@/hooks/use-route"
import { getCurrent, setCurrent } from "@/lib/current"
import { cn } from "@/lib/utils"

async function del(kind: "batch" | "tvc", id: string): Promise<{ recycled_to: string }> {
  const url = kind === "batch" ? `/api/batches/${encodeURIComponent(id)}` : `/api/tvc/${encodeURIComponent(id)}`
  const r = await fetch(url, { method: "DELETE" })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json()
}

/** 删除项目：挪进工作台回收站（data/_recycle），可以恢复 */
export function DeleteProject({ kind, id, name, icon, className, current, size = "lg" }: {
  kind: "batch" | "tvc"
  id: string
  name: string
  icon?: boolean          // true：侧边栏里的小垃圾桶图标
  className?: string
  current?: boolean       // 删的是当前打开的项目：删完跳回列表
  size?: "default" | "lg"
}) {
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)

  async function confirm() {
    setBusy(true)
    try {
      const r = await del(kind, id)
      setOpen(false)
      toast.success(`已删除「${name}」`, { description: `挪到了回收站：${r.recycled_to}，需要时可以挪回来` })
      window.dispatchEvent(new Event("jh:refresh"))
      if (kind === "batch" && getCurrent() === id) setCurrent(null)
      if (current) go(kind === "batch" ? { page: "projects" } : { page: "tvc" })
    } catch (e) {
      toast.error("删除失败", { description: String(e).replace(/^Error: /, "") })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AlertDialog open={open} onOpenChange={(v) => !busy && setOpen(v)}>
      <AlertDialogTrigger asChild>
        {icon ? (
          <button
            title="删除项目"
            onClick={(e) => e.stopPropagation()}
            className={cn("grid size-6 place-items-center rounded text-muted-foreground opacity-0 transition hover:bg-destructive/10 hover:text-destructive group-hover/sub:opacity-100 focus:opacity-100", className)}
          >
            <Trash2 className="size-3.5" />
          </button>
        ) : (
          <Button variant="ghost" size={size} className={cn("text-muted-foreground hover:bg-destructive/10 hover:text-destructive", className)}>
            <Trash2 />删除项目
          </Button>
        )}
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>删除项目「{name}」？</AlertDialogTitle>
          <AlertDialogDescription>
            {kind === "batch"
              ? "项目里的原始视频、识别结果、剪辑脚本和成片会一起挪到工作台回收站（data\\_recycle），不会立刻从硬盘上抹掉，需要时可以挪回来。"
              : "项目里的产品图、方案、分镜、视频段和成片会挪到工作台回收站（data\\_recycle），需要时可以挪回来。"}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>取消</AlertDialogCancel>
          <AlertDialogAction variant="destructive" disabled={busy} onClick={(e) => { e.preventDefault(); confirm() }}>
            {busy && <Loader2 className="animate-spin" />}删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

/** 打开了一个不存在（或刚被删掉）的项目时显示，而不是一直转圈 */
export function ProjectMissing({ kind, name }: { kind: "batch" | "tvc"; name: string }) {
  return (
    <div className="mx-auto grid max-w-md place-items-center px-6 pt-24 text-center">
      <div className="grid size-12 place-items-center rounded-xl bg-muted text-muted-foreground"><FolderX className="size-6" /></div>
      <div className="mt-4 text-lg font-semibold">项目「{name}」不存在</div>
      <p className="mt-1 text-sm text-muted-foreground">可能已经被删除（在工作台回收站 data\_recycle 里可以找回），或者链接写错了。</p>
      <Button variant="outline" className="mt-5" onClick={() => go(kind === "batch" ? { page: "projects" } : { page: "tvc" })}>
        <ArrowLeft />返回{kind === "batch" ? "全部项目" : "产品图生视频"}
      </Button>
    </div>
  )
}
