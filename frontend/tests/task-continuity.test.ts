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

test("取消正在上传的文件会中断传输，保留取消状态，并继续后续项目", async () => {
  const calls: { batch: string; transfer: ReturnType<typeof deferred<{ clip: string; size: number }>> }[] = []
  const completed: string[] = []
  let aborted = 0
  const store = new UploadTaskStore((batch) => {
    const transfer = deferred<{ clip: string; size: number }>()
    calls.push({ batch, transfer })
    return { promise: transfer.promise, abort: () => { aborted++; transfer.reject(new Error("已取消")) } }
  }, (item) => completed.push(item.file.name))
  store.add("one", "项目甲", [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")])
  store.add("two", "项目乙", [new File(["c"], "c.mp4")])
  const [current, queued] = store.getSnapshot("one").items
  store.cancel(current.key)
  store.cancel(queued.key)
  store.cancel(current.key) // 重复点击不重复中断。
  await setImmediate()
  assert.equal(aborted, 1)
  assert.deepEqual(store.getSnapshot("one").items.map((item) => item.status), ["cancelled", "cancelled"])
  assert.equal(store.getSnapshot("one").items[0].error, undefined)
  assert.deepEqual(calls.map((call) => call.batch), ["项目甲", "项目乙"])
  calls[1].transfer.resolve({ clip: "c.mp4", size: 1 })
  await setImmediate()
  assert.deepEqual(completed, ["c.mp4"])
  store.cancel(store.getSnapshot("two").items[0].key)
  assert.equal(store.getSnapshot("two").items[0].status, "done")
  store.clearBatchDone("项目甲")
  assert.equal(store.getSnapshot("one").items.length, 0)
  assert.equal(store.getSnapshot("two").items.length, 1)
})

test("取消后迟到的进度与成功响应不会覆盖状态，也不会回调上传成功", async () => {
  const transfer = deferred<{ clip: string; size: number }>()
  let progress!: (loaded: number, total: number) => void
  let completed = 0
  const store = new UploadTaskStore((_batch, _file, onProgress) => {
    progress = onProgress
    return { promise: transfer.promise, abort: () => {} }
  }, () => completed++)
  store.add("scope", "项目", [new File(["aaaa"], "a.mp4")])
  const key = store.getAll()[0].key
  store.cancel(key)
  progress(4, 4)
  transfer.resolve({ clip: "a.mp4", size: 4 })
  await setImmediate()
  assert.equal(store.getAll()[0].status, "cancelled")
  assert.equal(store.getAll()[0].loaded, 0)
  assert.equal(completed, 0)
})

test("失败项在切到另一个项目后仍重传到原项目，并保留上传编号防止重复", async () => {
  const calls: { batch: string; file: File; id?: string; transfer: ReturnType<typeof deferred<{ clip: string; size: number }>> }[] = []
  const uploaded: string[] = []
  const store = new UploadTaskStore((batch, file, progress, id) => {
    const transfer = deferred<{ clip: string; size: number }>()
    calls.push({ batch, file, id, transfer })
    progress(file.size / 2, file.size)
    return { promise: transfer.promise, abort: () => {} }
  }, (item) => uploaded.push(item.batch))
  const file = new File(["original"], "原素材.mp4")
  store.add("projects", "原项目", [file])
  const key = store.getSnapshot("projects").items[0].key
  calls[0].transfer.reject(new Error("网络中断"))
  await setImmediate()
  const unsubscribe = store.subscribe(() => {})
  unsubscribe()
  store.add("projects", "新项目", [new File(["next"], "新素材.mp4")])
  assert.equal(store.retry(key), true)
  assert.equal(store.retry(key), false) // 快速连点不能重复入队。
  assert.equal(store.retry("不存在"), false)
  const queued = store.getSnapshot("projects").items.find((item) => item.key === key)!
  assert.deepEqual([queued.status, queued.loaded, queued.error, queued.speed], ["queued", 0, undefined, undefined])
  calls[1].transfer.resolve({ clip: "新素材.mp4", size: 4 })
  await setImmediate()
  assert.deepEqual(calls.map((call) => call.batch), ["原项目", "新项目", "原项目"])
  assert.equal(calls[2].file, file)
  assert.equal(calls[0].id, calls[2].id)
  calls[2].transfer.resolve({ clip: file.name, size: file.size })
  await setImmediate()
  assert.equal(store.getBatchSnapshot("原项目").items[0].status, "done")
  assert.equal(store.retry(key), false)
  assert.deepEqual(uploaded, ["新项目", "原项目"])
})

test("批量重试只处理选定队列中的失败项，连续失败后仍可再次重试", async () => {
  const calls: { batch: string; transfer: ReturnType<typeof deferred<{ clip: string; size: number }>> }[] = []
  const store = new UploadTaskStore((batch) => {
    const transfer = deferred<{ clip: string; size: number }>()
    calls.push({ batch, transfer })
    return { promise: transfer.promise, abort: () => {} }
  })
  store.add("one", "项目甲", [new File(["a"], "a.mp4"), new File(["b"], "b.mp4")])
  calls[0].transfer.reject(new Error("离线")); await setImmediate()
  calls[1].transfer.reject(new Error("离线")); await setImmediate()
  store.add("two", "项目乙", [new File(["c"], "c.mp4")])
  calls[2].transfer.reject(new Error("离线")); await setImmediate()
  const keys = store.getSnapshot("one").items.map((item) => item.key)
  assert.equal(store.retryFailed([...keys, keys[0]]), 2)
  calls[3].transfer.reject(new Error("再次中断")); await setImmediate()
  calls[4].transfer.resolve({ clip: "b.mp4", size: 1 }); await setImmediate()
  assert.equal(store.getSnapshot("two").items[0].status, "error")
  assert.equal(store.retryFailed(keys), 1)
  calls[5].transfer.resolve({ clip: "a.mp4", size: 1 }); await setImmediate()
  assert.deepEqual(store.getSnapshot("one").items.map((item) => item.status), ["done", "done"])
  assert.equal(calls.length, 6)
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
