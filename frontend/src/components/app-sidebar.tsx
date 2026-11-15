import { useEffect, useState } from "react"
import { AudioLines, Bot, Cpu, FolderOpen, HardDrive, Sparkles } from "lucide-react"
import { motion } from "motion/react"

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar"
import { useJobs } from "@/hooks/use-jobs"
import { go, href, type Route } from "@/hooks/use-route"
import { api, type Batch, type Gpu, type Info, type TtsEngine } from "@/lib/api"
import { minutes } from "@/lib/format"
import { cn } from "@/lib/utils"

function GpuCard({ gpu, busy }: { gpu: Gpu | null; busy: boolean }) {
  const [used, total] = (gpu?.mem ?? "0/0").replace(" MB", "").split("/").map(Number)
  const pct = total ? (used / total) * 100 : 0
  return (
    <div className="rounded-xl border border-sidebar-border bg-muted/60 p-3 group-data-[collapsible=icon]:hidden">
      <div className="flex items-center gap-2 text-[13px]">
        <span className={cn("size-2 rounded-full", busy ? "animate-pulse bg-warn shadow-[0_0_0_4px_oklch(0.78_0.14_70/18%)]" : gpu ? "bg-ok shadow-[0_0_0_4px_oklch(0.72_0.13_160/15%)]" : "bg-muted-foreground")} />
        <span className="font-semibold">{gpu?.mode === "local" || !gpu ? "本机 GPU" : "AutoDL"}</span>
        <span className="ml-auto text-xs text-muted-foreground">{busy ? "工作中" : gpu ? "空闲" : "检测中"}</span>
      </div>
      <div className="mt-1.5 mb-2 truncate text-xs text-muted-foreground">{gpu?.name ?? "…"}</div>
      <div className="h-1.5 overflow-hidden rounded-full bg-foreground/8">
        <motion.div className="gold-gradient h-full" initial={false} animate={{ width: `${pct}%` }} transition={{ type: "spring", stiffness: 120, damping: 20 }} />
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-muted-foreground tabular">
        <span>显存 {used ? (used / 1024).toFixed(1) : "-"} / {total ? (total / 1024).toFixed(0) : "-"} GB</span>
        <span>占用 {gpu?.util ?? "-"}</span>
      </div>
    </div>
  )
}

function BatchProgress({ b }: { b: Batch }) {
  const t = b.clips ? b.transcribed / b.clips : 0
  const r = b.scripts ? b.rendered / b.scripts : 0
  const seg = (p: number) => (
    <span className="h-[3px] flex-1 overflow-hidden rounded-full bg-foreground/10">
      <span className="block h-full bg-primary" style={{ width: `${p * 100}%` }} />
    </span>
  )
  return (
    <span className="mt-1.5 flex w-full gap-1">
      {seg(t)}
      {seg(b.scripts ? 1 : 0)}
      {seg(r)}
    </span>
  )
}

export function AppSidebar({ route }: { route: Route }) {
  const { active, version } = useJobs()
  const [gpu, setGpu] = useState<Gpu | null>(null)
  const [info, setInfo] = useState<Info | null>(null)
  const [batches, setBatches] = useState<Batch[]>([])
  const [engine, setEngine] = useState<TtsEngine | null>(null)
  useEffect(() => {
    const load = () => api.ttsEngines().then((r) => setEngine(r.engines.find((x) => x.id === r.default) ?? null)).catch(() => {})
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    api.info().then(setInfo).catch(() => {})
    const load = () => api.gpu().then(setGpu).catch(() => {})
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [])
  useEffect(() => {
    api.batches().then(setBatches).catch(() => {})
  }, [version, route])

  const current = route.page === "batch" || route.page === "script" ? route.batch : null

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild className="hover:bg-transparent">
              <a href={href({ page: "home" })}>
                <div className="gold-gradient grid size-8 shrink-0 place-items-center rounded-lg text-[15px] font-extrabold text-primary-foreground shadow-md shadow-primary/30">
                  巨
                </div>
                <div className="grid leading-tight">
                  <span className="font-bold tracking-wide">巨航剪辑工作台</span>
                  <span className="text-xs text-muted-foreground">口播素材 → 粤语带货短视频</span>
                </div>
              </a>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
        <GpuCard gpu={gpu} busy={active.length > 0 || !!gpu?.busy} />
      </SidebarHeader>

      <SidebarContent className="scrollbar-thin">
        <SidebarGroup>
          <SidebarGroupLabel>创作</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={route.page === "tvc" || route.page === "tvc-project"}
                  tooltip="产品图生视频"
                  onClick={() => go({ page: "tvc" })}
                  className="data-[active=true]:ring-1 data-[active=true]:ring-primary/35"
                >
                  <Sparkles className="text-gold-ink" />
                  <span className="font-medium">产品图生视频</span>
                  <span className="ml-auto rounded-full bg-primary/15 px-1.5 text-[10px] text-gold-ink group-data-[collapsible=icon]:hidden">云端</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarGroup>
          <SidebarGroupLabel>口播剪辑 · 拍摄批次</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1">
              {batches.map((b) => (
                <SidebarMenuItem key={b.batch}>
                  <SidebarMenuButton
                    isActive={current === b.batch}
                    tooltip={`${b.batch} · ${b.clips} 条素材`}
                    onClick={() => go({ page: "batch", batch: b.batch, tab: "scripts" })}
                    className="relative isolate h-auto flex-col items-start gap-0 py-2.5 transition-colors data-active:bg-transparent group-data-[collapsible=icon]:items-center"
                  >
                    {current === b.batch && (
                      <motion.span
                        layoutId="batch-active"
                        className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent ring-1 ring-primary/35"
                        transition={{ type: "spring", stiffness: 380, damping: 32 }}
                      />
                    )}
                    <span className="flex w-full items-baseline gap-2">
                      <FolderOpen className="size-4 shrink-0 self-center text-muted-foreground group-data-[active=true]/menu-button:text-primary" />
                      <span className="text-[15px] font-bold group-data-[collapsible=icon]:hidden">{b.batch}</span>
                      <span className="ml-auto text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                        {b.clips} 条{b.total_seconds ? ` · ${minutes(b.total_seconds)} 分` : ""}
                      </span>
                    </span>
                    <span className="pl-6 text-xs text-muted-foreground group-data-[collapsible=icon]:hidden">
                      {b.scripts ? `${b.scripts} 条脚本 · ${b.rendered} 条已出片` : b.transcribed ? `已识别 ${b.transcribed}/${b.clips}` : "未处理"}
                    </span>
                    <span className="w-full pl-6 group-data-[collapsible=icon]:hidden">
                      <BatchProgress b={b} />
                    </span>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="group-data-[collapsible=icon]:hidden">
        <div className="grid gap-1.5 border-t border-sidebar-border px-2 pt-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-2"><AudioLines className="size-3.5" />配音 <b className="ml-auto flex items-center gap-1.5 font-medium text-foreground/80">{engine && <span className={cn("size-1.5 rounded-full", engine.running ? "bg-ok" : engine.available ? "bg-primary" : "bg-muted-foreground/40")} title={engine.running ? "运行中" : engine.note} />}{engine?.name ?? info?.tts ?? "-"}</b></div>
          <div className="flex items-center gap-2"><Bot className="size-3.5" />出脚本 <b className="ml-auto font-medium text-foreground/80">{info?.llm ?? "-"}</b>{info && !info.llm_ready && <span className="text-warn">未填 Key</span>}</div>
          <div className="flex items-center gap-2"><HardDrive className="size-3.5" />素材和成片都在本机</div>
          <div className="flex items-center gap-2"><Cpu className="size-3.5" />审核确认前不会出片</div>
        </div>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
