// 产品图生视频（产品贴字 TVC）接口
import type { Job } from "./api"

export interface TvcKeyframePlan {
  id: number
  role: string
  shot: string
  on_screen_text: string[]
  image_prompt: string
}

export interface TvcSegmentPlan {
  id: number
  from: number
  to: number
  seconds: number
  video_prompt: string
}

export interface TvcPlan {
  title: string
  concept: string
  category: string
  typography_ref: string
  typography_reason: string
  product_anchor: string
  texts: string[]
  keyframes: TvcKeyframePlan[]
  segments: TvcSegmentPlan[]
  bgm: string
}

export interface TvcItem {
  id: number
  file: string | null
  seed: number | null
  status: "pending" | "done" | "stale"
}

export interface TvcBrief {
  product: string
  brand: string
  selling_points: string
  notes: string
}

export interface TvcProject {
  id: string
  created: number
  updated: number
  brief: TvcBrief
  product_file: string
  stage: string
  caption: string
  plan: TvcPlan | null
  keyframes: TvcItem[]
  segments: TvcItem[]
  final: string | null
}

export interface TvcSummary {
  id: string
  created: number
  updated: number
  brief: TvcBrief
  stage: string
  final: string | null
  title: string
  cover: string | null
}

export interface CloudStatus {
  connected: boolean
  gpu?: string
  vram_total?: number
  vram_free?: number
  running?: number
  pending?: number
  error?: string
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init })
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText)
  return r.json() as Promise<T>
}

const e = encodeURIComponent

export const tvcApi = {
  cloud: () => req<CloudStatus>("/api/cloud/status"),
  list: () => req<TvcSummary[]>("/api/tvc"),
  get: (id: string) => req<TvcProject>(`/api/tvc/${e(id)}`),
  create: (body: TvcBrief & { image: string; filename: string; until?: "keyframes" | "final" }) =>
    req<{ project: TvcProject; job: Job | null }>("/api/tvc", { method: "POST", body: JSON.stringify(body) }),
  savePlan: (id: string, plan: TvcPlan) => req<TvcProject>(`/api/tvc/${e(id)}/plan`, { method: "PUT", body: JSON.stringify(plan) }),
  run: (id: string, until: "keyframes" | "final") => req<Job>(`/api/tvc/${e(id)}/run`, { method: "POST", body: JSON.stringify({ until }) }),
  replan: (id: string) => req<Job>(`/api/tvc/${e(id)}/replan`, { method: "POST" }),
  keyframe: (id: string, k: number) => req<Job>(`/api/tvc/${e(id)}/keyframes/${k}`, { method: "POST" }),
  segment: (id: string, s: number) => req<Job>(`/api/tvc/${e(id)}/segments/${s}`, { method: "POST" }),
  compose: (id: string) => req<Job>(`/api/tvc/${e(id)}/compose`, { method: "POST" }),
}

export const tvcFile = (id: string, name: string) => `/api/tvc/${e(id)}/file/${e(name)}`
