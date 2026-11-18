import { api } from "./api.ts"
import { todayName } from "./current.ts"
import { isVideo } from "./upload.ts"
import type { UploadItem } from "./upload-tasks.ts"

/** 每次调用都创建新项目；同名文件夹再次上传也不会复用旧项目。 */
export async function createUploadProject(files: File[], folder: string | null, create = api.createBatch): Promise<string> {
  const videos = files.filter(isVideo)
  if (!videos.length) throw new Error("没有找到视频，支持 .mov / .mp4 / .m4v")
  const hint = folder || (videos.length === 1 ? videos[0].name.replace(/\.[^.]+$/, "") : todayName())
  const base = Array.from(hint.replace(/[\\/:*?"<>|]/g, "").split("").filter((char) => char.charCodeAt(0) >= 32).join("").trim().replace(/^[ .]+|[ .]+$/g, "") || todayName())
  for (let index = 1; index <= 1000; index++) {
    const suffix = index === 1 ? "" : `_${index}`
    const name = base.slice(0, 60 - suffix.length).join("").trimEnd() + suffix
    try {
      return (await create(name)).batch
    } catch (error) {
      if (!String(error).includes("已经有叫")) throw error
    }
  }
  throw new Error("同名项目太多，请换一个文件夹名")
}

export function groupUploads(items: UploadItem[]) {
  const groups = new Map<string, UploadItem[]>()
  for (const item of items) {
    const group = groups.get(item.batch)
    if (group) group.push(item)
    else groups.set(item.batch, [item])
  }
  return groups
}
