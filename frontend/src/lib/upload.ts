// 上传视频素材：用 XMLHttpRequest 直接 PUT 文件内容，能拿到上传进度；服务端边收边写硬盘
export interface UploadResult {
  clip: string
  size: number
}

export function uploadClip(batch: string, file: File, onProgress: (loaded: number, total: number) => void): { promise: Promise<UploadResult>; abort: () => void } {
  const xhr = new XMLHttpRequest()
  const promise = new Promise<UploadResult>((resolve, reject) => {
    xhr.open("PUT", `/api/batches/${encodeURIComponent(batch)}/upload?filename=${encodeURIComponent(file.name)}`)
    xhr.setRequestHeader("Content-Type", "application/octet-stream")
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.total || file.size)
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText))
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
  return /\.(mov|mp4|m4v)$/i.test(f.name)
}

export function fmtSize(n: number) {
  if (n >= 2 ** 30) return `${(n / 2 ** 30).toFixed(2)} GB`
  if (n >= 2 ** 20) return `${(n / 2 ** 20).toFixed(0)} MB`
  return `${(n / 1024).toFixed(0)} KB`
}
