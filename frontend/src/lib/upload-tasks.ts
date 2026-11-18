import { uploadClip } from "./upload.ts"

export interface UploadItem {
  key: string
  scope: string
  batch: string
  file: File
  loaded: number
  status: "queued" | "uploading" | "done" | "error" | "cancelled"
  error?: string
  speed?: number
  created: number
}

interface Snapshot { items: UploadItem[]; batch: string | null }
type Transport = typeof uploadClip

/** 请求与队列属于应用，不属于任何一个页面；每条素材固定绑定自己的项目。 */
export class UploadTaskStore {
  private items: UploadItem[] = []
  private pending: string[] = []
  private current: { key: string; abort: () => void } | null = null
  private pumping = false
  private snapshots = new Map<string, Snapshot>()
  private batchSnapshots = new Map<string, Snapshot>()
  private listeners = new Set<() => void>()
  private transport: Transport
  private onUploaded: (item: UploadItem) => void

  constructor(transport: Transport = uploadClip, onUploaded: (item: UploadItem) => void = () => {}) {
    this.transport = transport
    this.onUploaded = onUploaded
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  getAll = () => this.items
  getSnapshot = (scope: string): Snapshot => {
    let snapshot = this.snapshots.get(scope)
    if (!snapshot) {
      snapshot = { items: [], batch: null }
      this.snapshots.set(scope, snapshot)
    }
    return snapshot
  }
  getBatchSnapshot = (batch: string): Snapshot => {
    if (!this.batchSnapshots.has(batch)) this.batchSnapshots.set(batch, { items: this.items.filter((item) => item.batch === batch), batch })
    return this.batchSnapshots.get(batch)!
  }

  private publish(scope: string, batch = this.getSnapshot(scope).batch) {
    this.snapshots.set(scope, { items: this.items.filter((item) => item.scope === scope), batch })
    for (const name of this.batchSnapshots.keys()) this.batchSnapshots.set(name, { items: this.items.filter((item) => item.batch === name), batch: name })
    this.listeners.forEach((listener) => listener())
  }
  private patch(key: string, value: Partial<UploadItem>) {
    const item = this.items.find((row) => row.key === key)
    if (!item) return
    this.items = this.items.map((row) => row.key === key ? { ...row, ...value } : row)
    this.publish(item.scope)
  }

  add(scope: string, batch: string, files: File[]) {
    if (!batch) throw new Error("请先创建项目")
    const added = files.map((file): UploadItem => ({
      key: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`, scope, batch, file, loaded: 0, status: "queued", created: Date.now(),
    }))
    this.items = [...this.items, ...added]
    this.pending.push(...added.map((item) => item.key))
    this.publish(scope, batch)
    void this.pump()
  }

  private async pump() {
    if (this.pumping) return
    this.pumping = true
    try {
      while (this.pending.length) {
        const key = this.pending.shift()!
        const item = this.items.find((row) => row.key === key)
        if (!item || item.status !== "queued") continue
        this.patch(key, { status: "uploading" })
        const started = performance.now()
        try {
          const transfer = this.transport(item.batch, item.file, (loaded) => {
            if (this.items.find((row) => row.key === key)?.status !== "uploading") return
            const seconds = (performance.now() - started) / 1000
            this.patch(key, { loaded, speed: seconds > 0.5 ? loaded / seconds : undefined })
          }, item.key)
          this.current = { key, abort: transfer.abort }
          await transfer.promise
          if (this.items.find((row) => row.key === key)?.status !== "uploading") continue
          this.patch(key, { loaded: item.file.size, status: "done" })
          this.onUploaded(item)
        } catch (error) {
          if (this.items.find((row) => row.key === key)?.status === "uploading") {
            this.patch(key, { status: "error", error: String(error).replace(/^Error: /, "") })
          }
        } finally {
          this.current = null
        }
      }
    } finally {
      this.pumping = false
    }
  }

  cancel(key: string) {
    const item = this.items.find((row) => row.key === key)
    if (!item || (item.status !== "queued" && item.status !== "uploading")) return
    this.pending = this.pending.filter((pending) => pending !== key)
    this.patch(key, { status: "cancelled", speed: undefined, error: undefined })
    if (this.current?.key === key) this.current.abort()
  }
  retry(key: string) {
    const item = this.items.find((row) => row.key === key)
    if (!item || item.status !== "error") return false
    this.patch(key, { status: "queued", loaded: 0, speed: undefined, error: undefined })
    this.pending.push(key)
    void this.pump()
    return true
  }
  retryFailed(keys: string[]) {
    return keys.reduce((count, key) => count + Number(this.retry(key)), 0)
  }
  clearDone(scope: string) {
    this.items = this.items.filter((row) => row.scope !== scope || !["done", "cancelled"].includes(row.status))
    this.publish(scope)
  }
  clearBatchDone(batch: string) {
    const scopes = new Set(this.items.filter((item) => item.batch === batch && ["done", "cancelled"].includes(item.status)).map((item) => item.scope))
    this.items = this.items.filter((item) => item.batch !== batch || !["done", "cancelled"].includes(item.status))
    scopes.forEach((scope) => this.publish(scope))
  }
  reset(scope: string) {
    if (this.items.some((row) => row.scope === scope && ["queued", "uploading"].includes(row.status))) return
    this.items = this.items.filter((row) => row.scope !== scope)
    this.publish(scope, null)
  }
}

export const uploadTasks = new UploadTaskStore(uploadClip, (item) => {
  window.dispatchEvent(new CustomEvent("jh:upload-complete", { detail: { scope: item.scope, batch: item.batch } }))
  window.dispatchEvent(new Event("jh:refresh"))
})
