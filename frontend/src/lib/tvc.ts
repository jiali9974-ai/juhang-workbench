// 产品图生视频接口：口播带货（presenter，照参考作品）和产品贴字 TVC（typography）两种风格
import type { Job } from "./api"

export type TvcStyle = "presenter" | "typography"

/** 口播带货的一个镜头：主播出镜或手持特写，配一到两句粤语 */
export interface TvcShot {
  id: number
  type: "presenter" | "closeup"
  role: string
  shot: string
  seconds: number
  lines: string[]
  image_prompt: string
  video_prompt: string
}

export interface PresenterPlan {
  style: "presenter"
  title: string
  concept: string
  scene: string
  shots: TvcShot[]
  bgm: string
}

export interface TvcVoice {
  file: string
  dur: number
  sig: string
  lines: { text: string; start: number; end: number }[]
}

export interface Presenter {
  file: string
  prompt: string
  seed: number | null
  source: "generated" | "uploaded"
  updated: number
}

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
  seconds?: number | null
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
  style?: TvcStyle
  presenter_file?: string
  voice?: (TvcVoice | null)[]
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
  style?: TvcStyle
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
  create: (body: TvcBrief & { image: string; filename: string; style: TvcStyle; until?: "keyframes" | "final" }) =>
    req<{ project: TvcProject; job: Job | null }>("/api/tvc", { method: "POST", body: JSON.stringify(body) }),
  savePlan: (id: string, plan: TvcPlan | PresenterPlan) => req<TvcProject>(`/api/tvc/${e(id)}/plan`, { method: "PUT", body: JSON.stringify(plan) }),
  run: (id: string, until: "keyframes" | "final") => req<Job>(`/api/tvc/${e(id)}/run`, { method: "POST", body: JSON.stringify({ until }) }),
  replan: (id: string) => req<Job>(`/api/tvc/${e(id)}/replan`, { method: "POST" }),
  keyframe: (id: string, k: number) => req<Job>(`/api/tvc/${e(id)}/keyframes/${k}`, { method: "POST" }),
  segment: (id: string, s: number) => req<Job>(`/api/tvc/${e(id)}/segments/${s}`, { method: "POST" }),
  compose: (id: string) => req<Job>(`/api/tvc/${e(id)}/compose`, { method: "POST" }),
  voice: (id: string) => req<Job>(`/api/tvc/${e(id)}/voice`, { method: "POST" }),
  presenter: () => req<{ presenter: Presenter | null; default_prompt: string }>("/api/tvc_presenter"),
  presenterGenerate: (prompt: string) => req<Job>("/api/tvc_presenter/generate", { method: "POST", body: JSON.stringify({ prompt }) }),
  presenterUpload: (image: string, filename: string) =>
    req<Presenter>("/api/tvc_presenter/upload", { method: "POST", body: JSON.stringify({ image, filename }) }),
}

export const presenterFile = (name: string) => `/api/tvc_presenter/file/${e(name)}`

export const tvcFile = (id: string, name: string) => `/api/tvc/${e(id)}/file/${e(name)}`
