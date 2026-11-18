import assert from "node:assert/strict"
import test from "node:test"

import { createUploadProject, groupUploads } from "../src/lib/upload-projects.ts"
import { filesFromDrop } from "../src/lib/upload.ts"
import { UploadTaskStore } from "../src/lib/upload-tasks.ts"
import { jobOf } from "../src/lib/current.ts"
import type { Job } from "../src/lib/api.ts"

function entry(file: File) {
  return { isFile: true, isDirectory: false, name: file.name, file: (resolve: (file: File) => void) => resolve(file) }
}

function directory(name: string, children: unknown[]) {
  return { isDirectory: true, isFile: false, name, createReader: () => {
    let offset = 0
    return { readEntries: (resolve: (entries: unknown[]) => void) => {
      const chunk = children.slice(offset, offset + 100)
      offset += chunk.length
      resolve(chunk)
    } }
  } }
}

test("一次拖入多个文件夹时分别分组，子文件夹保留在所属根目录，超过100个文件也会读完", async () => {
  const first = Array.from({ length: 105 }, (_, index) => entry(new File([String(index)], `${index}.mp4`)))
  const nested = new File(["nested"], "子目录视频.mov")
  const loose = new File(["loose"], "单独视频.mp4")
  const roots = [directory("文件夹甲", [...first, directory("子目录", [entry(nested)])]), directory("文件夹乙", [entry(new File(["b"], "0.mp4"))]), entry(loose)]
  const transfer = { files: [], items: roots.map((root) => ({ kind: "file", webkitGetAsEntry: () => root })) } as unknown as DataTransfer
  const groups = await filesFromDrop(transfer)
  assert.deepEqual(groups.map((group) => group.folder), ["文件夹甲", "文件夹乙", null])
  assert.equal(groups[0].files.length, 106)
  assert.equal(groups[0].files.at(-1), nested)
  assert.equal(groups[1].files.length, 1)
  assert.deepEqual(groups[2].files, [loose])
})

test("连续与同时上传同名文件夹始终建立新项目，不会复用正在上传的项目", async () => {
  const names = new Set<string>()
  const create = async (name: string) => {
    await Promise.resolve()
    if (names.has(name)) throw new Error(`已经有叫「${name}」的项目了`)
    names.add(name)
    return { batch: name, job: null }
  }
  const file = new File(["video"], "同名.mp4")
  const one = await createUploadProject([file], "同一文件夹", create)
  const [two, three] = await Promise.all([
    createUploadProject([file], "同一文件夹", create), createUploadProject([file], "同一文件夹", create),
  ])
  assert.deepEqual([one, two, three], ["同一文件夹", "同一文件夹_2", "同一文件夹_3"])
  const uploads = new UploadTaskStore(() => ({ promise: new Promise(() => {}), abort: () => {} }))
  for (const batch of [one, two, three]) uploads.add("home", batch, [file])
  assert.deepEqual([...groupUploads(uploads.getAll()).keys()], [one, two, three])
  assert.deepEqual(uploads.getAll().map((item) => item.batch), [one, two, three])
})

test("超长文件夹名为重名编号预留空间，非法字符被去掉，空文件夹不会创建项目", async () => {
  const calls: string[] = []
  const create = async (name: string) => {
    calls.push(name)
    if (calls.length === 1) throw new Error("已经有叫这个名字的项目")
    return { batch: name, job: null }
  }
  const name = await createUploadProject([new File(["v"], "视频.mp4")], ` ${"目录".repeat(40)}:? `, create)
  assert.equal(Array.from(name).length, 60)
  assert.ok(name.endsWith("_2"))
  assert.notEqual(calls[0], calls[1])
  await assert.rejects(createUploadProject([new File(["text"], "说明.txt")], "空文件夹", create), /没有找到视频/)
  assert.equal(calls.length, 2)
})

test("一个项目创建失败不会阻断下一次上传，也不会误归到旧项目", async () => {
  const files = [new File(["v"], "视频.mp4")]
  await assert.rejects(createUploadProject(files, "甲", async () => { throw new Error("网络中断") }), /网络中断/)
  assert.equal(await createUploadProject(files, "乙", async (batch) => ({ batch, job: null })), "乙")
})

test("同名文件夹加编号后，任务归属按完整项目名区分", () => {
  const job = (kind: string, title: string) => ({ kind, title }) as Job
  assert.equal(jobOf(job("auto", "目录_2 一键出片"), "目录"), false)
  assert.equal(jobOf(job("auto", "目录_2 一键出片"), "目录_2"), true)
  assert.equal(jobOf(job("render", "目录_2_01 出片"), "目录"), false)
  assert.equal(jobOf(job("render", "目录_2_01 出片"), "目录_2"), true)
  assert.equal(jobOf(job("render", "目录_01 出片"), "目录"), true)
})
