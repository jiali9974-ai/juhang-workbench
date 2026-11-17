import assert from "node:assert/strict"
import { mock, test } from "node:test"
import { api, urls } from "../src/lib/api.ts"

test("新接口直接展示已完成成片，不依赖整个生成任务完成", async (t) => {
  const completed = [{ batch: "项目", id: "第一条", title: "第一条", updated: 1, size: 100 }]
  const fetcher = mock.method(globalThis, "fetch", async (path: string, options?: RequestInit) => {
    assert.equal(path, "/api/outputs")
    assert.equal(options?.cache, "no-store")
    return Response.json(completed)
  })
  t.after(() => fetcher.mock.restore())
  assert.deepEqual(await api.outputs(), completed)
  assert.equal(fetcher.mock.callCount(), 1)
})

test("旧服务仍在生成时，逐条纳入已完成且文件存在的成片；重生成时更新封面版本", async (t) => {
  let secondReady = false
  let firstReady = true
  const fetcher = mock.method(globalThis, "fetch", async (path: string) => {
    if (path === "/api/outputs") return Response.json({ detail: "Not Found" }, { status: 404 })
    if (path === "/api/batches") return Response.json([{ batch: "上传项目" }])
    if (path === "/api/jobs") return Response.json([
      { kind: "auto", title: "上传项目 一键出片", status: "running" },
      { kind: "render", title: "重出 出片", status: "queued" },
    ])
    assert.equal(path, `/api/batches/${encodeURIComponent("上传项目")}/scripts`)
    return Response.json([
      { batch: "上传项目", id: "第一条", title: "已完成", status: firstReady ? "rendered" : "approved", has_output: true },
      { batch: "上传项目", id: "第二条", title: "正在生成", status: secondReady ? "rendered" : "approved", has_output: true },
      { batch: "上传项目", id: "缺失", title: "已被移走", status: "rendered", has_output: false },
      { batch: "上传项目", id: "重出", title: "正在重做", status: "rendered", has_output: true },
    ])
  })
  t.after(() => fetcher.mock.restore())
  const initial = await api.outputs()
  assert.deepEqual(initial.map((video) => video.id), ["第一条"])
  assert.equal((await api.outputs())[0].updated, initial[0].updated)
  secondReady = true
  assert.deepEqual(new Set((await api.outputs()).map((video) => video.id)), new Set(["第一条", "第二条"]))
  firstReady = false
  assert.deepEqual((await api.outputs()).map((video) => video.id), ["第二条"])
  firstReady = true
  const now = mock.method(Date, "now", () => 1999999999999)
  t.after(() => now.mock.restore())
  assert.notEqual((await api.outputs()).find((video) => video.id === "第一条")?.updated, initial[0].updated)
})

test("同一时间的成片请求合并，服务故障会报错而不会误显示空库", async (t) => {
  const fetcher = mock.method(globalThis, "fetch", async () => Response.json({ detail: "service unavailable" }, { status: 503 }))
  t.after(() => fetcher.mock.restore())
  const first = api.outputs()
  const second = api.outputs()
  assert.equal(first, second)
  await assert.rejects(first, /service unavailable/)
  await assert.rejects(second, /service unavailable/)
  assert.equal(fetcher.mock.callCount(), 1)
})

test("旧预览服务删除临时文件后，浏览器保存的默认测试图仍可读取", async (t) => {
  const originalFetch = globalThis.fetch
  const image = new Uint8Array([255, 216, 255, 0, 1])
  const fetcher = mock.method(globalThis, "fetch", async (path: string, options?: RequestInit) => {
    if (path === "/api/look/preview") {
      assert.equal(JSON.parse(String(options?.body)).source, null)
      return Response.json({ kind: "face", original: "original.jpg", beauty: "beauty.jpg" })
    }
    assert.match(path, /^\/api\/look\/file\/(original|beauty)\.jpg$/)
    return new Response(image, { headers: { "Content-Type": "image/jpeg" } })
  })
  t.after(() => fetcher.mock.restore())
  const result = await api.lookPreview(null, "face", { enabled: true, normalize: false, smooth: .5, tone: 1, sharpen: 1 })
  t.after(() => { URL.revokeObjectURL(result.original); URL.revokeObjectURL(result.beauty) })
  assert.equal(result.source, "default")
  assert.equal(result.fallback, false)
  assert.match(result.beauty, /^blob:/)
  assert.equal(urls.lookFile(result.beauty), result.beauty)
  assert.deepEqual(new Uint8Array(await (await originalFetch(result.beauty)).arrayBuffer()), image)
})
