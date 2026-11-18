// 上传视频素材：用 XMLHttpRequest 直接 PUT 文件内容，能拿到上传进度；服务端边收边写硬盘
export interface UploadResult {
  clip: string
  size: number
}

export function uploadClip(batch: string, file: File, onProgress: (loaded: number, total: number) => void, uploadId?: string): { promise: Promise<UploadResult>; abort: () => void } {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<UploadResult>((resolve, reject) => {
    const query = new URLSearchParams({ filename: file.name, expected_size: String(file.size) })
    if (uploadId) query.set("upload_id", uploadId)
    xhr.open("PUT", `/api/batches/${encodeURIComponent(batch)}/upload?${query}`)
    xhr.setRequestHeader("Content-Type", "application/octet-stream")
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total || file.size)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const result: UploadResult = JSON.parse(xhr.responseText)
          if (typeof result.clip !== "string" || result.size !== file.size) throw new Error("上传结果不完整，请重试")
          resolve(result)
        } catch (error) {
          reject(error instanceof SyntaxError ? new Error("服务器返回异常，请重试") : error)
        }
      }
      else {
        let msg = xhr.statusText
        try { msg = JSON.parse(xhr.responseText).detail || msg } catch { /* 保持原状态文字 */ }
        reject(new Error(msg))
      }
    }
    xhr.onerror = () => reject(new Error("网络中断"))
    xhr.onabort = () => reject(new Error("已取消"))
    xhr.send(file)
  })
  return { promise, abort: () => xhr.abort() }
}

export const VIDEO_ACCEPT = ".mov,.mp4,.m4v,video/quicktime,video/mp4"

export function isVideo(f: File) {
  // ._IMG_5818.MOV 是苹果电脑拷贝时留下的隐藏附属文件，不是视频
  return /\.(mov|mp4|m4v)$/i.test(f.name) && !f.name.startsWith("._")
}

/**
 * 拖进来的东西里取出全部文件：拖的是文件夹就把里面（含子文件夹）的文件都找出来。
 * folder：只拖了一个文件夹时是它的名字，用来给项目起名。
 * 注意：必须在 drop 事件里直接调用（第一个 await 之前就把条目取出来了，事件结束后就取不到了）。
 */
export async function filesFromDrop(dt: DataTransfer): Promise<{ files: File[]; folder: string | null }> {
  const entries = Array.from(dt.items ?? [])
    .filter((i) => i.kind === "file")
    .map((i) => i.webkitGetAsEntry?.() ?? null)
    .filter((x): x is FileSystemEntry => !!x)
  const plain = Array.from(dt.files)
  if (!entries.length) return { files: plain, folder: null }

  const files: File[] = []
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (entry.isFile) {
      files.push(await new Promise<File>((res, rej) => (entry as FileSystemFileEntry).file(res, rej)))
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader()
      // readEntries 一次最多给 100 个，要一直读到空为止
      for (;;) {
        const chunk = await new Promise<FileSystemEntry[]>((res, rej) => reader.readEntries(res, rej))
        if (!chunk.length) break
        for (const e of chunk) await walk(e)
      }
    }
  }
  for (const e of entries) await walk(e)
  const only = entries.length === 1 && entries[0].isDirectory ? entries[0].name : null
  return { files, folder: only }
}

/** 「选择文件夹」选出来的文件：取最外层文件夹名 */
export function folderOf(files: File[]): string | null {
  const p = (files[0] as File & { webkitRelativePath?: string })?.webkitRelativePath
  return p && p.includes("/") ? p.split("/")[0] : null
}

export function fmtSize(n: number) {
  if (n >= 2 ** 30) return `${(n / 2 ** 30).toFixed(2)} GB`
  if (n >= 2 ** 20) return `${(n / 2 ** 20).toFixed(0)} MB`
  return `${(n / 1024).toFixed(0)} KB`
}
