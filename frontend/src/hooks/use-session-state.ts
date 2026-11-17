import { useSyncExternalStore } from "react"
import { sessionCell } from "@/lib/session-state-store"

/** 页面切换只移除订阅；已经发出的任务仍可写回状态，返回页面时接着显示。 */
export function useSessionState<T>(key: string, initial: T | (() => T)) {
  const record = sessionCell(key, initial)
  const value = useSyncExternalStore(record.subscribe, record.read, record.read)
  return [value, record.write] as const
}
