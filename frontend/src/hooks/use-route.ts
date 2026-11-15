import { useEffect, useState } from "react"

// 用地址栏 # 记住当前页面，刷新和前进后退都不会丢：
//   #/                    首页
//   #/b/9.23              批次页
//   #/b/9.23/clips        批次页 · 素材库
//   #/b/9.23/s/9.23_01    审核某条脚本
//   #/tvc                 产品图生视频：项目列表 + 新建
//   #/tvc/<项目号>        产品图生视频：项目详情
export type Route =
  | { page: "home" }
  | { page: "batch"; batch: string; tab: "scripts" | "clips" }
  | { page: "script"; batch: string; id: string }
  | { page: "tvc" }
  | { page: "tvc-project"; id: string }

function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent).filter(Boolean)
  if (parts[0] === "b" && parts[1]) {
    if (parts[2] === "s" && parts[3]) return { page: "script", batch: parts[1], id: parts[3] }
    return { page: "batch", batch: parts[1], tab: parts[2] === "clips" ? "clips" : "scripts" }
  }
  if (parts[0] === "tvc") return parts[1] ? { page: "tvc-project", id: parts[1] } : { page: "tvc" }
  return { page: "home" }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  if (r.page === "batch") return `#/b/${e(r.batch)}${r.tab === "clips" ? "/clips" : ""}`
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
