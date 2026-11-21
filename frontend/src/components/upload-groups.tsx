import { UploadList } from "@/components/upload-queue"
import { uploadTasks, type UploadItem } from "@/lib/upload-tasks"
import { groupUploads } from "@/lib/upload-projects"
import { cn } from "@/lib/utils"

/** 项目名始终可见，上传、重试、取消和清理都限定在对应项目。 */
export function UploadGroups({ items, submitted, clearable = true, className }: {
  items: UploadItem[]; submitted?: string[]; clearable?: boolean; className?: string
}) {
  if (!items.length) return null
  const groups = [...groupUploads(items)]
  return (
    <section className={cn("mt-5 flex max-h-[min(36svh,22rem)] min-h-0 flex-col overflow-hidden rounded-2xl border bg-card", className)}>
      <div className="flex shrink-0 items-center justify-between gap-3 border-b px-4 py-3 text-sm">
        <span className="font-medium">上传记录</span>
        <span className="text-xs text-muted-foreground tabular">{groups.length} 个项目 · {items.length} 个视频</span>
      </div>
      <div role="region" aria-label="上传项目和文件" tabIndex={0} className="scroll-region min-h-0 flex-1 space-y-4 p-3">
        {groups.map(([batch, files]) => (
          <section key={batch} aria-label={`素材项目：${batch}`}>
            <div className="flex items-center justify-between gap-3 px-1 text-sm">
              <span className="min-w-0 truncate font-medium" title={batch}>{batch}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{files.length} 个视频{submitted?.includes(batch) ? " · 已提交生成" : ""}</span>
            </div>
            <UploadList items={files} onCancel={(key) => uploadTasks.cancel(key)}
              onRetry={(key) => uploadTasks.retry(key)}
              onRetryFailed={() => uploadTasks.retryFailed(files.map((file) => file.key))}
              onClear={clearable ? () => uploadTasks.clearBatchDone(batch) : undefined} scrollable={false} />
          </section>
        ))}
      </div>
    </section>
  )
}
