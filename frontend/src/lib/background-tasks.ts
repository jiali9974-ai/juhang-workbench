export interface BackgroundTask { id: string; title: string; created: number }

/** 在组件卸载后继续跟踪请求；相同请求正在运行时复用它，避免重复提交。 */
export class BackgroundTaskStore {
  private tasks: BackgroundTask[] = []
  private pending = new Map<string, Promise<unknown>>()
  private listeners = new Set<() => void>()
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  getSnapshot = () => this.tasks
  run<T>(key: string, title: string, action: () => Promise<T>): Promise<T> {
    const current = this.pending.get(key)
    if (current) return current as Promise<T>
    const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`
    this.tasks = [...this.tasks, { id, title, created: Date.now() }]
    const request = Promise.resolve().then(action).finally(() => {
      this.pending.delete(key)
      this.tasks = this.tasks.filter((task) => task.id !== id)
      this.listeners.forEach((listener) => listener())
    })
    this.pending.set(key, request)
    this.listeners.forEach((listener) => listener())
    return request
  }
}

export const backgroundTasks = new BackgroundTaskStore()

interface CachedResult<T> { status: "idle" | "loading" | "done" | "error"; data: T | null; error: string | null }
const idle: CachedResult<never> = { status: "idle", data: null, error: null }
const results = new Map<string, CachedResult<unknown>>()
const listeners = new Set<() => void>()
export const previewCache = {
  subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } },
  get<T>(key: string | null): CachedResult<T> { return (key ? results.get(key) : null) as CachedResult<T> ?? idle },
  start<T>(key: string, action: () => Promise<T>) {
    const previous = results.get(key)
    if (previous?.status === "loading" || previous?.status === "done") return
    const update = (state: CachedResult<T>) => { results.set(key, state); listeners.forEach((listener) => listener()) }
    update({ status: "loading", data: null, error: null })
    void Promise.resolve().then(action).then((data) => update({ status: "done", data, error: null }),
      (error) => update({ status: "error", data: null, error: String(error).replace(/^Error: /, "") }))
  },
}
