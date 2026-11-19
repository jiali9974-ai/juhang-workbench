import type { Job, OutputVideo, Script } from "./api.ts"

export const outputKey = (video: Pick<OutputVideo, "batch" | "id">) => JSON.stringify([video.batch, video.id])
export interface SubtitleDraft { script: Script; saved: string[] }
export function subtitleChanges(draft: SubtitleDraft) {
  return draft.script.lines.flatMap((line, index) => line.subtitle === draft.saved[index] ? [] : [{
    index, clip: line.clip, start: line.start, end: line.end, previous: draft.saved[index], subtitle: line.subtitle,
  }])
}

/** 只提交当前成片列表中明确勾选的条目；部分失败保留失败项供重试。 */
export async function renderSelected(videos: OutputVideo[], keys: string[], submit: (batch: string, id: string) => Promise<Job>, onJob: (job: Job) => void) {
  const selected = new Set(keys), seen = new Set<string>()
  const accepted: string[] = [], failed: { key: string; title: string; error: string }[] = []
  for (const video of videos) {
    const key = outputKey(video)
    if (!selected.has(key) || seen.has(key)) continue
    seen.add(key)
    let job: Job
    try { job = await submit(video.batch, video.id) }
    catch (error) { failed.push({ key, title: video.title, error: String(error).replace(/^Error: /, "") }); continue }
    accepted.push(key)
    try { onJob(job) } catch { /* 已入队的任务不能因跟踪回调报错而被重复提交。 */ }
  }
  return { accepted, failed }
}
