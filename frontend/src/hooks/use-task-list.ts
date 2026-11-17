import { useSyncExternalStore } from "react"

import { useAllUploads } from "@/components/upload-queue"
import { useJobs } from "@/hooks/use-jobs"
import type { Job } from "@/lib/api"
import { backgroundTasks } from "@/lib/background-tasks"

/** 页面共用一份任务视图：后台生成、上传，以及尚未返回的预览/导出等请求。 */
export function useTaskList() {
  const { jobs: backend } = useJobs()
  const uploads = useAllUploads()
  const requests = useSyncExternalStore(backgroundTasks.subscribe, backgroundTasks.getSnapshot, backgroundTasks.getSnapshot)
  const uploading: Job[] = uploads.map((item) => ({
    id: `upload:${item.key}`, kind: "upload", title: `${item.file.name} 上传`,
    status: item.status === "uploading" ? "running" : item.status,
    progress: item.file.size ? item.loaded / item.file.size : 0,
    message: item.status === "done" ? "上传完成" : item.status === "queued" ? "等待上传" : `上传到「${item.batch}」`,
    error: item.error ?? "", result: null, created: item.created / 1000, finished: null,
  }))
  const pending: Job[] = requests.map((task) => ({
    id: `request:${task.id}`, kind: "request", title: task.title, status: "running", progress: 0,
    message: task.title, error: "", result: null, created: task.created / 1000, finished: null,
  }))
  const jobs = [...backend, ...uploading, ...pending].sort((a, b) => b.created - a.created)
  const active = jobs.filter((job) => job.status === "queued" || job.status === "running")
  return { jobs, active }
}
