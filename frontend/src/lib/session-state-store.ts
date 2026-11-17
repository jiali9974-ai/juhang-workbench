import type { SetStateAction } from "react"

class SessionCell<T> {
  private value: T
  private listeners = new Set<() => void>()
  constructor(value: T) { this.value = value }
  read = () => this.value
  subscribe = (listener: () => void) => {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }
  write = (next: SetStateAction<T>) => {
    const value = typeof next === "function" ? (next as (previous: T) => T)(this.value) : next
    if (Object.is(value, this.value)) return
    this.value = value
    this.listeners.forEach((listener) => listener())
  }
}

const cells = new Map<string, SessionCell<unknown>>()
export function sessionCell<T>(key: string, initial: T | (() => T)): SessionCell<T> {
  if (!cells.has(key)) cells.set(key, new SessionCell(typeof initial === "function" ? (initial as () => T)() : initial) as SessionCell<unknown>)
  return cells.get(key) as SessionCell<T>
}
