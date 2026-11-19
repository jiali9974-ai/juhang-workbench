// 和工作台后端（FastAPI）通信的类型与请求
import { backgroundTasks } from "./background-tasks.ts"
import type { EditorFont, GraphicsSettings } from "./graphics"

export type Lang = "yue" | "zh" | string
export type Role = "hook" | "product" | "cta"
export type ScriptStatus = "draft" | "approved" | "rendered"

export interface Batch {
  batch: string
  clips: number
  transcribed: number
  total_seconds: number | null
  scripts: number
  outputs: number
  rendered: number
}

export interface Line {
  ref?: string
  clip: string
  start: number
  end: number
  src_lang: Lang
  src_text: string
  subtitle: string
  role: Role
  zoom: number | null
}

export interface Script {
  id: string
  batch: string
  title: string
  status: ScriptStatus
  lines: Line[]
  duration?: number
  has_output?: boolean
}

export interface Clip {
  clip: string
  duration: number
  transcribed: boolean
  lang: Record<string, number>
  sentences: number
  preview_text?: string
}

export interface Sentence {
  start: number
  end: number
  lang: Lang
  text: string
}

export interface Transcript {
  clip: string
  duration: number
  sentences: Sentence[]
}

export interface Job {
  id: string
  kind: string
  title: string
  status: "queued" | "running" | "done" | "error" | "cancelled"
  cancel_requested?: boolean
  progress: number
  message: string
  stage?: string | null
  completed_stages?: string[]
  result: unknown
  error: string
  created: number
  finished: number | null
}

export interface Gpu {
  mode: string
  busy: boolean
  state?: string
  name?: string
  mem?: string
  util?: string
}

export interface Info {
  llm: string
  llm_ready: boolean
  gpu_mode: string
  min_seconds: number | null
  max_seconds: number | null
}

class ApiError extends Error {
  readonly status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const execute = async () => {
    const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init })
    if (!r.ok) {
      const body = await r.json().catch(() => ({}))
      const message = path.endsWith("/cancel") && (r.status === 405 || (r.status === 404 && body.detail === "Not Found"))
        ? "当前服务尚不支持取消任务，请在空闲时重启本地工作台后再试"
        : body.detail || r.statusText
      throw new ApiError(r.status, message)
    }
    return r.json() as Promise<T>
  }
  if (!init?.method || init.method === "GET" || path.endsWith("/cancel")) return execute()
  const title = path.endsWith("/api/look/preview") ? "生成美颜预览"
    : path === "/api/outputs/export" ? "导出成片"
    : path === "/api/pipeline/llm_models" ? "刷新模型列表"
    : path === "/api/pipeline/test_llm" ? "测试模型"
    : path === "/api/batches" ? "创建项目"
    : init.method === "DELETE" ? "删除文件"
    : init.method === "PUT" ? "保存设置" : "提交任务"
  return backgroundTasks.run(`${init.method}:${path}:${String(init.body ?? "")}`, title, execute)
}

const e = encodeURIComponent

/** 美颜调色强度：都是 0–1 */
export interface LookSettings {
  enabled: boolean
  /** 统一光线：不同素材先按老板肤色拉齐亮度和白平衡，再调色 */
  normalize: boolean
  smooth: number
  tone: number
  sharpen: number
}

/** 流程图：每一步的模型配置 */
export interface FieldOption {
  value: string
  label: string
  note?: string
  disabled?: boolean
}
export interface PipelineField {
  key: string | null            // null = 只展示，不能改
  label: string
  type: "select" | "list" | "text" | "toggle" | "info"
  value: string | string[] | boolean
  options: FieldOption[]
  note: string
  custom: boolean               // select 也可以自己填（大模型名）
}
export interface PipelineStep {
  id: string
  title: string
  desc: string
  off?: boolean
  fields: PipelineField[]
}
export interface PipelineBranch {
  id: string
  title: string
  desc: string
  steps: PipelineStep[]
}
export interface Pipeline {
  root: string
  branches: PipelineBranch[]
  llm_ready: boolean
}

export interface OutputVideo {
  batch: string
  id: string
  title: string
  updated: number
  size: number
  cover_note?: string
}

const legacyOutputVersions = new Map<string, number>()
let pendingOutputs: Promise<OutputVideo[]> | null = null

async function loadOutputs(): Promise<OutputVideo[]> {
  try {
    return await request<OutputVideo[]>("/api/outputs", { cache: "no-store" })
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
  }
  // 老服务可能仍在出片，不能为了更新接口重启它；直接读取每条脚本的完成状态。
  const [batches, jobs] = await Promise.all([
    request<Batch[]>("/api/batches", { cache: "no-store" }),
    request<Job[]>("/api/jobs", { cache: "no-store" }),
  ])
  const projects = await Promise.all(batches.map(async ({ batch }) => {
    try {
      return await request<Script[]>(`/api/batches/${e(batch)}/scripts`, { cache: "no-store" })
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return [] // 刷新期间项目被删除。
      throw error
    }
  }))
  const active = jobs.filter((job) => job.status === "running" || job.status === "queued")
  const ready = projects.flat().filter((script) => script.status === "rendered" && script.has_output &&
    !active.some((job) => job.title === `${script.id} 出片`))
  const keys = new Set(ready.map((script) => JSON.stringify([script.batch, script.id])))
  for (const key of legacyOutputVersions.keys()) {
    if (!keys.has(key)) legacyOutputVersions.delete(key)
  }
  return ready.map((script) => {
    const key = JSON.stringify([script.batch, script.id])
    // 旧接口没有文件时间；以首次发现成片的时间标记封面版本，重新生成后更新。
    const updated = legacyOutputVersions.get(key) ?? Date.now() / 1000
    legacyOutputVersions.set(key, updated)
    return { batch: script.batch, id: script.id, title: script.title || script.id, updated, size: 0 }
  }).sort((a, b) => b.updated - a.updated || a.id.localeCompare(b.id))
}

function readOutputs() {
  if (!pendingOutputs) pendingOutputs = loadOutputs().finally(() => { pendingOutputs = null })
  return pendingOutputs
}

async function keepPreviewImage(name: string) {
  const response = await fetch(`/api/look/file/${e(name)}`, { cache: "no-store" })
  if (!response.ok) throw new Error("预览图片读取失败，请重试")
  return URL.createObjectURL(await response.blob())
}

export const api = {
  outputs: readOutputs,
  deleteOutput: (batch: string, id: string) =>
    request<{ ok: boolean }>(batch ? `/api/outputs/${e(batch)}/${e(id)}` : `/api/root_outputs/${e(id)}`, { method: "DELETE" }),
  exportOutputs: (items: Pick<OutputVideo, "batch" | "id">[]) =>
    request<{ url: string }>("/api/outputs/export", { method: "POST", body: JSON.stringify({ items }) }),
  pipeline: () => request<Pipeline>("/api/pipeline"),
  savePipeline: (changes: Record<string, unknown>) =>
    request<{ saved: Record<string, unknown>; pipeline: Pipeline }>("/api/pipeline", { method: "PUT", body: JSON.stringify({ changes }) }),
  refreshLlmModels: () => request<{ models: string[]; error: string }>("/api/pipeline/llm_models", { method: "POST" }),
  testLlm: (model: string) =>
    request<{ model: string; reply: string; seconds: number }>("/api/pipeline/test_llm", { method: "POST", body: JSON.stringify({ model }) }),
  info: () => request<Info>("/api/info"),
  gpu: () => request<Gpu>("/api/gpu"),
  batches: () => request<Batch[]>("/api/batches"),
  createBatch: (name: string, folder?: string) =>
    request<{ batch: string; job: Job | null }>("/api/batches", { method: "POST", body: JSON.stringify({ name, folder }) }),
  importFolder: (b: string, path: string) => request<Job>(`/api/batches/${e(b)}/import_folder`, { method: "POST", body: JSON.stringify({ path }) }),
  stats: (b: string) => request<{ stats: Record<string, number> }>(`/api/batches/${e(b)}/transcripts`).then((r) => r.stats),
  clips: (b: string) => request<Clip[]>(`/api/batches/${e(b)}/clips`),
  transcript: (b: string, clip: string) => request<Transcript>(`/api/batches/${e(b)}/transcripts/${e(clip)}`),
  scripts: (b: string) => request<Script[]>(`/api/batches/${e(b)}/scripts`),
  saveScript: (s: Script) =>
    request<{ ok: boolean }>(`/api/batches/${e(s.batch)}/scripts/${e(s.id)}`, { method: "PUT", body: JSON.stringify(s) }),
  deleteScript: (b: string, id: string) => request<{ ok: boolean }>(`/api/batches/${e(b)}/scripts/${e(id)}`, { method: "DELETE" }),
  transcribe: (b: string) => request<Job>(`/api/batches/${e(b)}/transcribe`, { method: "POST" }),
  generate: (b: string) => request<Job>(`/api/batches/${e(b)}/generate`, { method: "POST" }),
  render: (b: string, id: string) => request<Job>(`/api/batches/${e(b)}/scripts/${e(id)}/render`, { method: "POST" }),
  renderAll: (b: string, all = false) => request<Job[]>(`/api/batches/${e(b)}/render_all`, { method: "POST", body: JSON.stringify({ all }) }),
  /** 美颜调色强度（批量出片都用这个） */
  getLook: () => request<{ settings: LookSettings; defaults: LookSettings }>("/api/look"),
  getGraphics: () => request<{ settings: GraphicsSettings; defaults: GraphicsSettings; fonts: EditorFont[] }>("/api/graphics"),
  saveGraphics: (settings: GraphicsSettings) => request<{ settings: GraphicsSettings }>("/api/graphics", { method: "PUT", body: JSON.stringify(settings) }),
  uploadFont: (file: File) => request<{ font: EditorFont; fonts: EditorFont[] }>(`/api/fonts?filename=${e(file.name)}`, { method: "POST", body: file, headers: { "Content-Type": "application/octet-stream" } }),
  deleteFont: (id: string) => request<{ ok: boolean; fonts: EditorFont[] }>(`/api/fonts/${e(id)}`, { method: "DELETE" }),
  graphicsPreview: (settings: GraphicsSettings, source: Pick<OutputVideo, "batch" | "id"> | null, look: LookSettings) =>
    request<{ url: string }>("/api/graphics/preview", { method: "POST", body: JSON.stringify({ settings, source, look }) }),
  saveLook: (s: LookSettings) => request<{ settings: LookSettings }>("/api/look", { method: "PUT", body: JSON.stringify(s) }),
  lookPreview: async (source: Pick<OutputVideo, "batch" | "id"> | null, kind: "face" | "watch", settings: LookSettings) => {
    const result = await request<{ kind: "face" | "watch"; original: string; beauty: string; source?: "cover" | "default"; fallback?: boolean }>(
      "/api/look/preview", { method: "POST", body: JSON.stringify({ source, kind, settings }) })
    if (result.source) return { ...result, source: result.source, fallback: result.fallback ?? false }
    // 旧服务只保留最近一次的文件；在浏览器内保存图片，返回页面或调回之前的强度时仍能显示。
    const [original, beauty] = await Promise.all([keepPreviewImage(result.original), keepPreviewImage(result.beauty)])
    return { ...result, original, beauty, source: "default" as const, fallback: source !== null }
  },
  auto: (b: string) => request<Job>(`/api/batches/${e(b)}/auto`, { method: "POST" }),
  jobs: () => request<Job[]>("/api/jobs"),
  cancelJob: (id: string) => request<Job>(`/api/jobs/${e(id)}/cancel`, { method: "POST" }),
}

export const urls = {
  thumb: (b: string, clip: string, t: number) => `/api/thumb?batch=${e(b)}&clip=${e(clip)}&t=${t.toFixed(1)}`,
  // c=cover：缩略图改成做好的封面后换个地址，浏览器不再用以前缓存的截帧（服务端现在会带 no-cache）
  outputThumb: (b: string, id: string) => b ? `/api/output_thumb/${e(b)}/${e(id)}.jpg?c=cover` : `/api/root_output_thumb/${e(id)}.jpg?c=cover`,
  output: (b: string, id: string) => b ? `/api/outputs/${e(b)}/${e(id)}.mp4` : `/api/root_outputs/${e(id)}.mp4`,
  lookFile: (name: string) => name.startsWith("blob:") ? name : `/api/look/file/${e(name)}`,
  sourceClip: (b: string, l: Line) =>
    `/api/preview_clip?batch=${e(b)}&clip=${e(l.clip)}&start=${l.start}&end=${l.end}`,
}
