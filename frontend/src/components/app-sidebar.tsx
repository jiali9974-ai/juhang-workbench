import { useEffect, useState, type ReactNode } from "react"
import { AudioLines, Bot, ChevronRight, Clapperboard, FolderOpen, HardDrive, Loader2, Plus } from "lucide-react"
import { AnimatePresence, motion } from "motion/react"
import { toast } from "sonner"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { DeleteProject } from "@/components/delete-project"
import { Input } from "@/components/ui/input"
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
  useSidebar,
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

function MiniProgress({ parts }: { parts: number[] }) {
  return (
    <span className="mt-1 flex w-full gap-0.5">
      {parts.map((p, i) => (
        <span key={i} className="h-[3px] flex-1 overflow-hidden rounded-full bg-foreground/10">
          <span className="block h-full bg-primary transition-all duration-500" style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%` }} />
        </span>
      ))}
    </span>
  )
}


/** 可展开的一条主线：标题行 + 下拉的项目列表 */
function NavSection(props: {
  id: string
  icon: ReactNode
  title: string
  badge?: ReactNode
  active: boolean
  open: boolean
  onToggle: () => void
  onHome: () => void
  count: number
  children: ReactNode
}) {
  const { state } = useSidebar()
  const collapsed = state === "collapsed"
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        size="lg"
        tooltip={props.title}
        isActive={props.active}
        onClick={() => (collapsed ? props.onHome() : props.onToggle())}
        className="h-10 data-[active=true]:bg-sidebar-accent/70"
      >
        {props.icon}
        <span className="font-semibold">{props.title}</span>
        {props.badge}
        <span className="ml-auto rounded-full bg-muted px-1.5 text-[10px] text-muted-foreground tabular group-data-[collapsible=icon]:hidden">{props.count}</span>
        <motion.span animate={{ rotate: props.open ? 90 : 0 }} transition={{ duration: 0.2 }} className="text-muted-foreground group-data-[collapsible=icon]:hidden">
          <ChevronRight className="size-4" />
        </motion.span>
      </SidebarMenuButton>
      <AnimatePresence initial={false}>
        {props.open && !collapsed && (
          <motion.div
            key={props.id}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-1 ml-3.5 grid gap-0.5 border-l border-sidebar-border py-0.5 pl-2">{props.children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </SidebarMenuItem>
  )
}

function SubItem({ active, onClick, children, layoutKey, action }: { active: boolean; onClick: () => void; children: ReactNode; layoutKey: string; action?: ReactNode }) {
  return (
    <div className="group/sub relative">
      <button onClick={onClick} className={cn("relative isolate w-full rounded-md px-2 py-1.5 text-left transition-colors hover:bg-sidebar-accent/60", active && "text-sidebar-accent-foreground")}>
        {active && (
          <motion.span layoutId={layoutKey} className="absolute inset-0 -z-10 rounded-md bg-sidebar-accent ring-1 ring-primary/35" transition={{ type: "spring", stiffness: 380, damping: 32 }} />
        )}
        {children}
      </button>
      {action && <div className="absolute top-1 right-1">{action}</div>}
    </div>
  )
}

function NewButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[13px] font-medium text-gold-ink transition-colors hover:bg-primary/10">
      <Plus className="size-3.5" />{label}
    </button>
  )
}

function loadOpen(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem("jh.nav.open") || "") || { clips: true }
  } catch {
    return { clips: true }
  }
}

export function AppSidebar({ route }: { route: Route }) {
  const { active, version } = useJobs()
  const [gpu, setGpu] = useState<Gpu | null>(null)
  const [info, setInfo] = useState<Info | null>(null)
  const [batches, setBatches] = useState<Batch[]>([])
  const [engine, setEngine] = useState<TtsEngine | null>(null)
  const [open, setOpen] = useState<Record<string, boolean>>(loadOpen)
  const [newBatch, setNewBatch] = useState<{ show: boolean; name: string; folder: string; busy: boolean }>({ show: false, name: "", folder: "", busy: false })
  const { watch } = useJobs()

  useEffect(() => {
    try { localStorage.setItem("jh.nav.open", JSON.stringify(open)) } catch { /* 无痕模式等情况忽略 */ }
  }, [open])
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
  useEffect(() => {
    // 上传、加载文件夹完成后页面会发这个事件，侧边栏跟着刷新素材数量
    const on = () => {
      api.batches().then(setBatches).catch(() => {})
    }
    window.addEventListener("jh:refresh", on)
    return () => window.removeEventListener("jh:refresh", on)
  }, [])

  const curBatch = route.page === "batch" || route.page === "script" ? route.batch : null
  const toggle = (k: string) => setOpen((o) => ({ ...o, [k]: !o[k] }))

  async function createBatch() {
    const name = newBatch.name.trim()
    const folder = newBatch.folder.trim()
    if (!name && !folder) return toast.error("请填写项目名，或者填一个本机文件夹路径")
    setNewBatch((s) => ({ ...s, busy: true }))
    try {
      const r = await api.createBatch(name, folder || undefined)
      setNewBatch({ show: false, name: "", folder: "", busy: false })
      setOpen((o) => ({ ...o, clips: true }))
      if (r.job) {
        toast.success(`已新建项目「${r.batch}」，正在加载文件夹里的视频`)
        watch(r.job, (j) => {
          const res = j.result as { added: number; linked: number; copied: number }
          toast.success(`已加载 ${res.added} 个视频`, { description: res.linked ? `${res.linked} 个用硬链接（不占额外空间）` : undefined })
          api.batches().then(setBatches).catch(() => {})
        })
      } else {
        toast.success(`已新建项目「${r.batch}」`, { description: "把视频素材拖进页面，或选择文件夹加载" })
      }
      api.batches().then(setBatches).catch(() => {})
      go({ page: "batch", batch: r.batch, tab: "clips" })
    } catch (e) {
      toast.error("新建失败", { description: String(e).replace(/^Error: /, "") })
      setNewBatch((s) => ({ ...s, busy: false }))
    }
  }

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
                  <span className="text-xs text-muted-foreground">产品广告 · 口播带货短视频</span>
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
            <SidebarMenu className="gap-1.5">
              {/* 视频素材剪辑 */}
              <NavSection
                id="clips"
                icon={<Clapperboard className="text-gold-ink" />}
                title="视频素材剪辑"
                active={route.page === "batch" || route.page === "script" || route.page === "home"}
                open={!!open.clips}
                onToggle={() => toggle("clips")}
                onHome={() => go({ page: "home" })}
                count={batches.length}
              >
                <NewButton label="新建项目 / 加载文件夹" onClick={() => setNewBatch({ show: true, name: "", folder: "", busy: false })} />
                {batches.map((b) => (
                  <SubItem key={b.batch} layoutKey="nav-active" active={curBatch === b.batch} onClick={() => go({ page: "batch", batch: b.batch, tab: b.clips ? "scripts" : "clips" })}
                    action={<DeleteProject kind="batch" id={b.batch} name={b.batch} icon current={curBatch === b.batch} />}>
                    <span className="flex items-center gap-2">
                      <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{b.batch}</span>
                      <span className="text-[11px] text-muted-foreground tabular transition-opacity group-hover/sub:opacity-0">{b.clips} 条{b.total_seconds ? ` · ${minutes(b.total_seconds)}分` : ""}</span>
                    </span>
                    <span className="block pl-6 text-[11px] text-muted-foreground">
                      {!b.clips ? "还没有素材，点进去上传" : b.scripts ? `${b.scripts} 条脚本 · ${b.rendered} 条已出片` : b.transcribed ? `已识别 ${b.transcribed}/${b.clips}` : "未处理"}
                    </span>
                    {b.clips > 0 && (
                      <span className="block pl-6">
                        <MiniProgress parts={[b.clips ? b.transcribed / b.clips : 0, b.scripts ? 1 : 0, b.scripts ? b.rendered / b.scripts : 0]} />
                      </span>
                    )}
                  </SubItem>
                ))}
              </NavSection>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="group-data-[collapsible=icon]:hidden">
        <div className="grid gap-1.5 border-t border-sidebar-border px-2 pt-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-2"><AudioLines className="size-3.5" />配音 <b className="ml-auto flex items-center gap-1.5 font-medium text-foreground/80">{engine && <span className={cn("size-1.5 rounded-full", engine.running ? "bg-ok" : engine.available ? "bg-primary" : "bg-muted-foreground/40")} title={engine.running ? "运行中" : engine.note} />}{engine?.name ?? info?.tts ?? "-"}</b></div>
          <div className="flex items-center gap-2"><Bot className="size-3.5" />智能体 <b className="ml-auto font-medium text-foreground/80">{info?.llm ?? "-"}</b>{info && !info.llm_ready && <span className="text-warn">未填 Key</span>}</div>
          <div className="flex items-center gap-2"><HardDrive className="size-3.5" />素材和成片都在本机</div>
        </div>
      </SidebarFooter>
      <SidebarRail />

      {/* 新建素材剪辑项目 */}
      <AlertDialog open={newBatch.show} onOpenChange={(v) => !newBatch.busy && setNewBatch((s) => ({ ...s, show: v }))}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>新建视频素材剪辑项目</AlertDialogTitle>
            <AlertDialogDescription>填一个本机文件夹就能一键加载里面的视频；也可以建好后在项目页拖入视频或选择文件夹上传。然后点「一键成片」。</AlertDialogDescription>
          </AlertDialogHeader>
          <label className="grid gap-1.5 text-sm">项目名
            <Input
              autoFocus
              value={newBatch.name}
              onChange={(e) => setNewBatch((s) => ({ ...s, name: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && createBatch()}
              placeholder="例如：11.16 门店口播（填了文件夹可以不填，默认用文件夹名）"
            />
          </label>
          <label className="grid gap-1.5 text-sm">一键加载本机文件夹 <span className="text-xs text-muted-foreground">选填：这台电脑上放素材的文件夹，里面（含子文件夹）的视频会全部加进项目</span>
            <Input
              value={newBatch.folder}
              onChange={(e) => setNewBatch((s) => ({ ...s, folder: e.target.value }))}
              onKeyDown={(e) => e.key === "Enter" && createBatch()}
              placeholder={"例如：D:\\巨航\\素材\\素材\\9.29"}
              className="font-mono text-xs"
            />
          </label>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={newBatch.busy}>取消</AlertDialogCancel>
            <AlertDialogAction disabled={newBatch.busy} aria-busy={newBatch.busy} onClick={(e) => { e.preventDefault(); createBatch() }}>
              {newBatch.busy && <Loader2 className="animate-spin" />}新建
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Sidebar>
  )
}
