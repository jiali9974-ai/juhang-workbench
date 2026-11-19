import test from "node:test"
import assert from "node:assert/strict"
import { outputKey, renderSelected, subtitleChanges } from "../src/lib/frame-workflow.ts"
import type { Job, OutputVideo, Script } from "../src/lib/api.ts"

const video = (batch: string, id: string) => ({ batch, id, title: `${batch}-${id}`, size: 1, updated: 1 }) as OutputVideo
const job = (batch: string, id: string) => ({ id: `${batch}-${id}`, title: `${id} 出片` }) as Job

test("只重出明确勾选的成片，按项目与编号区分同名成片并去重", async () => {
  const videos = [video("甲", "01"), video("乙", "01"), video("甲", "02")]
  const called: string[] = []
  const selected = outputKey(videos[1])
  const result = await renderSelected([...videos, videos[1]], [selected, selected, "stale"], async (batch, id) => { called.push(`${batch}/${id}`); return job(batch, id) }, () => {})
  assert.deepEqual(called, ["乙/01"])
  assert.deepEqual(result.accepted, [selected])
  assert.deepEqual(result.failed, [])
})

test("部分入队失败只保留失败项重试，已提交任务不会因跟踪异常重复入队", async () => {
  const videos = [video("甲", "01"), video("甲", "02")]
  const result = await renderSelected(videos, videos.map(outputKey), async (batch, id) => { if (id === "02") throw new Error("网络波动"); return job(batch, id) }, () => { throw new Error("tracker") })
  assert.deepEqual(result.accepted, [outputKey(videos[0])])
  assert.deepEqual(result.failed.map((item) => item.key), [outputKey(videos[1])])
})

test("字幕补丁只包含改动的字幕与原句校验，不发送原声和剪辑字段", () => {
  const script = { id: "01", batch: "甲", lines: [
    { clip: "a.mov", start: 1, end: 2, subtitle: "更正后的字幕", src_text: "原声", keep: "保留原声" },
    { clip: "b.mov", start: 3, end: 4, subtitle: "不变" },
  ] } as unknown as Script
  assert.deepEqual(subtitleChanges({ script, saved: ["原字幕", "不变"] }), [
    { index: 0, clip: "a.mov", start: 1, end: 2, previous: "原字幕", subtitle: "更正后的字幕" },
  ])
})
