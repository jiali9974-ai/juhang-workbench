// 和工作台后端（FastAPI）通信的类型与请求

export type Lang = "yue" | "zh" | string
export type Role = "hook" | "product" | "cta"
export type VoiceMode = "auto" | "original" | "tts_all"
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
  voice_mode: VoiceMode
  status: ScriptStatus
  tts_engine?: string
  voice_source?: "original" | "fixed"
  voice_ref?: VoiceRef
  lines: Line[]
  duration?: number
  resolved_voice?: "original" | "tts_all"
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
  status: "queued" | "running" | "done" | "error"
  progress: number
  message: string
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

export interface VoiceRef {
  clip: string
  start: number
  end: number
  lang: string
  text: string
}

export interface TtsEngine {
  id: string
  name: string
  available: boolean
  running: boolean
  note: string
}

export interface Info {
  tts: string
  llm: string
  llm_ready: boolean
  gpu_mode: string
  min_seconds: number
  max_seconds: number
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail || r.statusText)
  }
  return r.json() as Promise<T>
}

const e = encodeURIComponent

/** 整条转好粤语的视频 */
export interface DubItem {
  clip: string
  id: string
  engine?: string | null
  min_speed?: number | null
  duration: number
  sentences: number
  max_speed: number
  updated: number
  size: number
}

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

export const api = {
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
  saveLook: (s: LookSettings) => request<{ settings: LookSettings }>("/api/look", { method: "PUT", body: JSON.stringify(s) }),
  lookPreview: (batch: string, kind: "face" | "watch", settings: LookSettings, index = 0) =>
    request<{ kind: "face" | "watch"; original: string; beauty: string; frames: string[]; index: number; count: number }>(
      "/api/look/preview", { method: "POST", body: JSON.stringify({ batch, kind, settings, index }) }),
  ttsPreview: (text: string, engine?: string, ctx?: { batch: string; script_id: string; voice_source?: string; voice_ref?: VoiceRef }) =>
    request<Job>("/api/tts/preview", { method: "POST", body: JSON.stringify({ text, engine, ...ctx }) }),
  voiceRef: (b: string, id: string) =>
    request<{ current: VoiceRef | null; candidates: VoiceRef[] }>(`/api/batches/${e(b)}/scripts/${e(id)}/voice_ref`),
  ttsEngines: () => request<{ default: string; engines: TtsEngine[] }>("/api/tts/engines"),
  auto: (b: string) => request<Job>(`/api/batches/${e(b)}/auto`, { method: "POST" }),
  /** 整条转粤语（不剪辑）：clips 不传就处理项目里全部视频 */
  dubFull: (b: string, clips?: string[], engine?: string) =>
    request<Job>(`/api/batches/${e(b)}/dub_full`, { method: "POST", body: JSON.stringify({ clips, engine }) }),
  dubs: (b: string) => request<DubItem[]>(`/api/batches/${e(b)}/dubs`),
  jobs: () => request<Job[]>("/api/jobs"),
}

export const urls = {
  thumb: (b: string, clip: string, t: number) => `/api/thumb?batch=${e(b)}&clip=${e(clip)}&t=${t.toFixed(1)}`,
  // c=cover：缩略图改成做好的封面后换个地址，浏览器不再用以前缓存的截帧（服务端现在会带 no-cache）
  outputThumb: (b: string, id: string) => `/api/output_thumb/${e(b)}/${e(id)}.jpg?c=cover`,
  output: (b: string, id: string) => `/api/outputs/${e(b)}/${e(id)}.mp4`,
  lookFile: (name: string) => `/api/look/file/${e(name)}`,
  sourceClip: (b: string, l: Line) =>
    `/api/preview_clip?batch=${e(b)}&clip=${e(l.clip)}&start=${l.start}&end=${l.end}`,
  ttsFile: (path: string) => `/api/tts/file?path=${e(path)}`,
  voiceRefFile: (b: string, r: VoiceRef) => `/api/voice_ref_file?batch=${e(b)}&clip=${e(r.clip)}&start=${r.start}&end=${r.end}`,
}
