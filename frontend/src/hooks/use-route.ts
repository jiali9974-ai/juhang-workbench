import { useEffect, useState } from "react"

// 用地址栏 # 记住当前页面，刷新和前进后退都不会丢：
//   #/                    首页：上传素材 → 开始
//   #/g                   所有成片：预览、多选、批量导出
//   #/g/9.23              旧链接兼容，同样打开所有成片
//   #/projects            项目列表
//   #/beauty              美颜设置（#/beauty/9.23：用这个项目的画面预览）
//   #/flow                流程图：每一步用什么模型，可以直接改
//   #/b/9.23              项目详情（素材、脚本）
//   #/b/9.23/clips        项目详情 · 素材库
//   #/b/9.23/s/9.23_01    审核某条脚本
export type BatchTab = "scripts" | "clips"

export type Route =
  | { page: "home" }
  | { page: "gen"; batch?: string }
  | { page: "projects" }
  | { page: "beauty"; batch?: string }
  | { page: "flow"; batch?: string; job?: string }
  | { page: "batch"; batch: string; tab: BatchTab }
  | { page: "script"; batch: string; id: string }

let lastFlow: Extract<Route, { page: "flow" }> | null = null
export const getLastFlow = () => lastFlow
export const getRoute = () => parse(window.location.hash)

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent).filter(Boolean)
  if (parts[0] === "g") return parts[1] ? { page: "gen", batch: parts[1] } : { page: "gen" }
  if (parts[0] === "projects") return { page: "projects" }
  if (parts[0] === "flow") return { page: "flow", batch: parts[1], job: parts[2] }
  if (parts[0] === "beauty") return parts[1] ? { page: "beauty", batch: parts[1] } : { page: "beauty" }
  if (parts[0] === "b" && parts[1]) {
    if (parts[2] === "s" && parts[3]) return { page: "script", batch: parts[1], id: parts[3] }
    return { page: "batch", batch: parts[1], tab: parts[2] === "clips" ? "clips" : "scripts" }
  }
  return { page: "home" }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  if (r.page === "gen") return r.batch ? `#/g/${e(r.batch)}` : "#/g"
  if (r.page === "projects") return "#/projects"
  if (r.page === "flow") return r.batch ? `#/flow/${e(r.batch)}${r.job ? `/${e(r.job)}` : ""}` : "#/flow"
  if (r.page === "beauty") return r.batch ? `#/beauty/${e(r.batch)}` : "#/beauty"
  if (r.page === "batch") return `#/b/${e(r.batch)}${r.tab === "scripts" ? "" : `/${r.tab}`}`
  if (r.page === "script") return `#/b/${e(r.batch)}/s/${e(r.id)}`
  return "#/"
}

export function go(r: Route) {
  if (r.page === "flow" && r.job) lastFlow = r
  window.location.hash = href(r)
}

/** 记住任务的流程入口；等待提交时用户已经切走，就继续任务而不抢回当前页面。 */
export function followTask(source: Route, batch: string, job: string) {
  const destination = { page: "flow", batch, job } as const
  lastFlow = destination
  if (href(getRoute()) === href(source)) go(destination)
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(window.location.hash))
    window.addEventListener("hashchange", on)
    return () => window.removeEventListener("hashchange", on)
  }, [])
  return route
}
