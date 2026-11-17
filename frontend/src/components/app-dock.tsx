// 底部居中的导航：生成 / 项目 / 美颜设置 / 流程图
import { useEffect, useState } from "react"
import { FolderOpen, Sparkles, Wand2, Workflow } from "lucide-react"
import { motion } from "motion/react"

import { Dock, DockIcon, DockItem, DockLabel } from "@/components/ui/dock"
import { go, type Route } from "@/hooks/use-route"
import { api, type Batch } from "@/lib/api"
import { pickCurrent } from "@/lib/current"
import { cn } from "@/lib/utils"

export function AppDock({ route }: { route: Route }) {
  const [batches, setBatches] = useState<Batch[]>([])
  useEffect(() => {
    const load = () => api.batches().then(setBatches).catch(() => {})
    load()
    window.addEventListener("jh:refresh", load)
    return () => window.removeEventListener("jh:refresh", load)
  }, [route])

  const items = [
    {
      key: "gen",
      label: "生成",
      icon: Sparkles,
      active: route.page === "gen",
      // 回到当前项目的生成页；一个项目都没有就去上传
      onClick: () => {
        const b = route.page === "batch" || route.page === "script" || route.page === "beauty" ? route.batch ?? pickCurrent(batches) : pickCurrent(batches)
        go(b ? { page: "gen", batch: b } : { page: "home" })
      },
    },
    {
      key: "projects",
      label: "项目",
      icon: FolderOpen,
      active: route.page === "projects" || route.page === "batch" || route.page === "script",
      onClick: () => go({ page: "projects" }),
    },
    {
      key: "beauty",
      label: "美颜设置",
      icon: Wand2,
      active: route.page === "beauty",
      onClick: () => go({ page: "beauty", batch: route.page === "gen" || route.page === "batch" || route.page === "script" ? route.batch : undefined }),
    },
    {
      key: "flow",
      label: "流程图 · 模型",
      icon: Workflow,
      active: route.page === "flow",
      onClick: () => go({ page: "flow" }),
    },
  ]

  return (
    <motion.nav
      initial={{ y: 40, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: 40, opacity: 0 }}
      transition={{ type: "spring", stiffness: 320, damping: 30 }}
      className="pointer-events-none fixed inset-x-0 bottom-2 z-40 flex justify-center"
    >
      <Dock className="pointer-events-auto items-end border bg-background/85 pb-3 shadow-[0_8px_30px_oklch(0_0_0/8%)] backdrop-blur-md" magnification={72}>
        {items.map((it) => (
          <DockItem
            key={it.key}
            label={it.label}
            active={it.active}
            onClick={it.onClick}
            className={cn(
              "aspect-square rounded-full transition-colors",
              it.active ? "bg-foreground text-background" : "bg-muted text-foreground/70 hover:text-foreground",
            )}
          >
            <DockLabel>{it.label}</DockLabel>
            <DockIcon><it.icon className="size-full" /></DockIcon>
          </DockItem>
        ))}
      </Dock>
    </motion.nav>
  )
}
