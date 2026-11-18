// 「当前项目」：最近一次开始生成或打开生成页的项目。底部导航的「生成」回到它。
import type { Batch, Job } from "./api"

const KEY = "jh.current"

export function getCurrent(): string | null {
  try {
    return localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function setCurrent(batch: string | null) {
  try {
    if (batch) localStorage.setItem(KEY, batch)
    else localStorage.removeItem(KEY)
  } catch {
    /* 无痕模式等情况忽略 */
  }
}

/** 当前项目还在就用它，否则用最近改过的项目（列表按修改时间倒序） */
export function pickCurrent(batches: Batch[]): string | null {
  const cur = getCurrent()
  if (cur && batches.some((b) => b.batch === cur)) return cur
  return batches[0]?.batch ?? null
}

/** 任务是不是这个项目的：「9.23 一键出片」「9.23_01 出片」「加载文件夹到 9.23」 */
export function jobOf(j: Job, batch: string) {
  return j.title.startsWith(`${batch} `) || j.title === `加载文件夹到 ${batch}`
    || (j.kind === "render" && j.title.startsWith(`${batch}_`) && /^\d+ 出片$/.test(j.title.slice(batch.length + 1)))
}

/** 默认项目名：今天的日期，和素材文件夹的习惯一致（11.17） */
export function todayName() {
  const d = new Date()
  return `${d.getMonth() + 1}.${d.getDate()}`
}
