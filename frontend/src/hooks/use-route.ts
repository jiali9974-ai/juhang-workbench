import { useEffect, useState } from "react"

// 用地址栏 # 记住当前页面，刷新和前进后退都不会丢：
//   #/                    首页：上传素材 → 开始
//   #/g/9.23              生成：进度 + 成片（左边文字、右边视频）
//   #/projects            项目列表
//   #/beauty              美颜设置（#/beauty/9.23：用这个项目的画面预览）
//   #/flow                流程图：每一步用什么模型，可以直接改
//   #/b/9.23              项目详情（素材、脚本、粤语版）
//   #/b/9.23/clips        项目详情 · 素材库
//   #/b/9.23/dub          项目详情 · 整条转粤语的成片
//   #/b/9.23/s/9.23_01    审核某条脚本
//   #/tvc                 产品图生视频：项目列表 + 新建
//   #/tvc/<项目号>        产品图生视频：项目详情
export type BatchTab = "scripts" | "clips" | "dub"

export type Route =
  | { page: "home" }
  | { page: "gen"; batch: string }
  | { page: "projects" }
  | { page: "beauty"; batch?: string }
  | { page: "flow" }
  | { page: "batch"; batch: string; tab: BatchTab }
  | { page: "script"; batch: string; id: string }
  | { page: "tvc" }
  | { page: "tvc-project"; id: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent).filter(Boolean)
  if (parts[0] === "g" && parts[1]) return { page: "gen", batch: parts[1] }
  if (parts[0] === "projects") return { page: "projects" }
  if (parts[0] === "flow") return { page: "flow" }
  if (parts[0] === "beauty") return parts[1] ? { page: "beauty", batch: parts[1] } : { page: "beauty" }
  if (parts[0] === "b" && parts[1]) {
    if (parts[2] === "s" && parts[3]) return { page: "script", batch: parts[1], id: parts[3] }
    return { page: "batch", batch: parts[1], tab: parts[2] === "clips" ? "clips" : parts[2] === "dub" ? "dub" : "scripts" }
  }
  if (parts[0] === "tvc") return parts[1] ? { page: "tvc-project", id: parts[1] } : { page: "tvc" }
  return { page: "home" }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  if (r.page === "gen") return `#/g/${e(r.batch)}`
  if (r.page === "projects") return "#/projects"
  if (r.page === "flow") return "#/flow"
  if (r.page === "beauty") return r.batch ? `#/beauty/${e(r.batch)}` : "#/beauty"
  if (r.page === "batch") return `#/b/${e(r.batch)}${r.tab === "scripts" ? "" : `/${r.tab}`}`
  if (r.page === "script") return `#/b/${e(r.batch)}/s/${e(r.id)}`
  if (r.page === "tvc") return "#/tvc"
  if (r.page === "tvc-project") return `#/tvc/${e(r.id)}`
  return "#/"
}

export function go(r: Route) {
  window.location.hash = href(r)
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
