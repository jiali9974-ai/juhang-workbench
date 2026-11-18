import { UploadList } from "@/components/upload-queue"
import { uploadTasks, type UploadItem } from "@/lib/upload-tasks"
import { groupUploads } from "@/lib/upload-projects"

/** 项目名始终可见，上传、重试、取消和清理都限定在对应项目。 */
export function UploadGroups({ items, maxVisibleItems, submitted, clearable = true }: {
  items: UploadItem[]; maxVisibleItems?: number; submitted?: string[]; clearable?: boolean
}) {
  return (
    <div className="mt-5 space-y-5">
      {[...groupUploads(items)].map(([batch, files]) => (
        <section key={batch} aria-label={`素材项目：${batch}`}>
          <div className="flex items-center justify-between gap-3 px-1 text-sm">
            <span className="min-w-0 truncate font-medium" title={batch}>{batch}</span>
            <span className="shrink-0 text-xs text-muted-foreground">{files.length} 个视频{submitted?.includes(batch) ? " · 已提交生成" : ""}</span>
          </div>
          <UploadList items={files} onCancel={(key) => uploadTasks.cancel(key)}
            onRetry={(key) => uploadTasks.retry(key)}
            onRetryFailed={() => uploadTasks.retryFailed(files.map((file) => file.key))}
            onClear={clearable ? () => uploadTasks.clearBatchDone(batch) : undefined} maxVisibleItems={maxVisibleItems} />
        </section>
      ))}
    </div>
  )
}
