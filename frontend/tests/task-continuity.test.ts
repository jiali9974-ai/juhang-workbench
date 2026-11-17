import assert from "node:assert/strict"
import { setImmediate } from "node:timers/promises"
import test from "node:test"

import { UploadTaskStore } from "../src/lib/upload-tasks.ts"
import { BackgroundTaskStore, previewCache } from "../src/lib/background-tasks.ts"
import { sessionCell } from "../src/lib/session-state-store.ts"

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test("切走并取消页面订阅后，上传继续，返回时恢复进度，文件始终进入原项目", async () => {
  const calls: { batch: string; file: File; transfer: ReturnType<typeof deferred<{ clip: string; size: number }>> }[] = []
  let aborted = 0
  const store = new UploadTaskStore((batch, file, progress) => {
    const transfer = deferred<{ clip: string; size: number }>()
    calls.push({ batch, file, transfer })
    progress(1, file.size)
    return { promise: transfer.promise, abort: () => { aborted++; transfer.reject(new Error("已取消")) } }
  })
  const unsubscribe = store.subscribe(() => {})
  store.add("projects", "项目甲", [new File(["aaaa"], "a.mp4"), new File(["bbbb"], "b.mp4")])
  unsubscribe()
  store.add("batch:乙", "项目乙", [new File(["cccc"], "c.mp4")])
  assert.equal(store.getSnapshot("projects").items[0].loaded, 1)
  assert.equal(store.getSnapshot("projects").items[0].status, "uploading")
  calls[0].transfer.resolve({ clip: "a.mp4", size: 4 })
  await setImmediate()
  assert.deepEqual(calls.map((call) => call.batch), ["项目甲", "项目甲"])
  const remounted = store.subscribe(() => {})
  assert.deepEqual(store.getSnapshot("projects").items.map((item) => item.status), ["done", "uploading"])
  assert.deepEqual(store.getBatchSnapshot("项目甲").items.map((item) => item.status), ["done", "uploading"])
  calls[1].transfer.resolve({ clip: "b.mp4", size: 4 })
  await setImmediate()
  calls[2].transfer.resolve({ clip: "c.mp4", size: 4 })
  await setImmediate()
  assert.deepEqual(calls.map((call) => call.batch), ["项目甲", "项目甲", "项目乙"])
  assert.equal(store.getAll().filter((item) => item.status === "done").length, 3)
  assert.equal(aborted, 0)
  store.clearBatchDone("项目甲")
  assert.equal(store.getSnapshot("projects").items.length, 0)
  assert.equal(store.getBatchSnapshot("项目乙").items.length, 1)
  remounted()
})

test("只取消指定素材，取消排队文件不会中断另一个正在上传的文件", async () => {
  const transfers: ReturnType<typeof deferred<{ clip: string; size: number }>>[] = []
  let aborted = 0
  const store = new UploadTaskStore(() => {
    const transfer = deferred<{ clip: string; size: number }>()
    transfers.push(transfer)
    return { promise: transfer.promise, abort: () => { aborted++; transfer.reject(new Error("已取消")) } }
  })
  store.add("scope", "项目", [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")])
  store.cancel(store.getSnapshot("scope").items[1].key)
  assert.equal(aborted, 0)
  transfers[0].resolve({ clip: "a.mp4", size: 1 })
  await setImmediate()
  assert.equal(transfers.length, 1)
  assert.equal(store.getSnapshot("scope").items[0].status, "done")
})

test("某个文件上传失败后仍继续后续文件", async () => {
  const transfers: ReturnType<typeof deferred<{ clip: string; size: number }>>[] = []
  const store = new UploadTaskStore(() => {
    const transfer = deferred<{ clip: string; size: number }>()
    transfers.push(transfer)
    return { promise: transfer.promise, abort: () => {} }
  })
  store.add("scope", "项目", [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")])
  transfers[0].reject(new Error("网络故障"))
  await setImmediate()
  transfers[1].resolve({ clip: "b.mp4", size: 1 })
  await setImmediate()
  assert.deepEqual(store.getSnapshot("scope").items.map((item) => item.status), ["error", "done"])
})

test("导出等请求在页面订阅移除后继续，返回期间重复提交会复用同一请求", async () => {
  const store = new BackgroundTaskStore()
  const completion = deferred<string>()
  let requests = 0
  const action = () => { requests++; return completion.promise }
  const unsubscribe = store.subscribe(() => {})
  const original = store.run("export:selected", "导出成片", action)
  unsubscribe()
  assert.equal(store.getSnapshot().length, 1)
  const returned = store.run("export:selected", "导出成片", action)
  await setImmediate()
  assert.equal(requests, 1)
  completion.resolve("download-url")
  assert.deepEqual(await Promise.all([original, returned]), ["download-url", "download-url"])
  assert.equal(store.getSnapshot().length, 0)
})

test("美颜预览在切走后完成，返回时使用结果而非重复发起计算", async () => {
  const completion = deferred<{ image: string }>()
  let calls = 0
  const action = () => { calls++; return completion.promise }
  const unsubscribe = previewCache.subscribe(() => {})
  previewCache.start("fixture-beauty", action)
  unsubscribe()
  previewCache.start("fixture-beauty", action)
  assert.equal(previewCache.get("fixture-beauty").status, "loading")
  completion.resolve({ image: "ready.jpg" })
  await setImmediate()
  assert.equal(calls, 1)
  assert.deepEqual(previewCache.get("fixture-beauty").data, { image: "ready.jpg" })
  previewCache.start("fixture-beauty", action)
  assert.equal(calls, 1)
})

test("页面未订阅时的任务回写会在返回后显示，且不会重置保存中的状态", () => {
  const original = sessionCell("fixture-saving", false)
  const unsubscribe = original.subscribe(() => {})
  original.write(true)
  unsubscribe()
  assert.equal(sessionCell("fixture-saving", false).read(), true)
  original.write(false)
  assert.equal(sessionCell("fixture-saving", true).read(), false)
})
