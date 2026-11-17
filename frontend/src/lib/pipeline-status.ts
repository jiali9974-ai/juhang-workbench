import type { Job } from "./api"

export const CLIP_JOBS = ["auto", "generate", "transcribe", "render"]

/** 老任务兼容；新任务直接使用后台上报的实际步骤。 */
export function pipelineStage(job: Job): string | null {
  if (job.stage) return job.stage
  if (job.status === "done") return "done"
  if (job.kind === "transcribe") return "asr"
  if (job.kind === "generate") return /脚本/.test(job.message) ? "script" : "asr"
  if (job.kind === "auto" && job.progress < 2 / 3) return job.progress < 1 / 3 ? "asr" : "script"
  if (/封面/.test(job.message)) return "cover"
  if (/配音/.test(job.message)) return "tts"
  if (/片段|口误/.test(job.message)) return "look"
  return job.kind === "auto" || job.kind === "render" ? "render" : null
}
