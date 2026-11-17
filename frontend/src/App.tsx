import { AnimatePresence, MotionConfig } from "motion/react"

import { AppDock } from "@/components/app-dock"
import { JobsDock } from "@/components/jobs-dock"
import { Page } from "@/components/motion"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { JobsProvider } from "@/hooks/use-jobs"
import { href, useRoute } from "@/hooks/use-route"
import { FEATURES } from "@/lib/features"
import { BatchPage } from "@/pages/batch-page"
import { BeautyPage } from "@/pages/beauty-page"
import { FlowPage } from "@/pages/flow-page"
import { GenPage } from "@/pages/gen-page"
import { ProjectsPage } from "@/pages/projects-page"
import { ScriptEditor } from "@/pages/script-editor"
import { StartPage } from "@/pages/start-page"
import { TvcHome } from "@/pages/tvc-home"
import { TvcProjectPage } from "@/pages/tvc-project"

// 布局：首页只有上传框；开始生成之后的页面底部都有居中的导航（生成 / 项目 / 美颜设置 / 流程图）。
// 以前的左侧边栏（components/app-sidebar.tsx）和顶栏不再使用。
export default function App() {
  const raw = useRoute()
  // 产品图生视频先不做：它的地址（#/tvc…）直接当首页处理
  const route = !FEATURES.productVideo && (raw.page === "tvc" || raw.page === "tvc-project") ? ({ page: "home" } as const) : raw
  // 项目详情页切换标签不算换页，不播放整页动画
  const pageKey = route.page === "batch" ? `batch/${route.batch}` : href(route)
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={200}>
        <JobsProvider>
          <main className="min-h-svh bg-background">
            <AnimatePresence mode="wait" initial={false}>
              <Page key={pageKey}>
                {route.page === "home" && <StartPage />}
                {route.page === "gen" && <GenPage batch={route.batch} />}
                {route.page === "projects" && <ProjectsPage />}
                {route.page === "beauty" && <BeautyPage batch={route.batch} />}
                {route.page === "flow" && <FlowPage />}
                {route.page === "batch" && <BatchPage batch={route.batch} tab={route.tab} />}
                {route.page === "script" && <ScriptEditor batch={route.batch} id={route.id} />}
                {route.page === "tvc" && <TvcHome />}
                {route.page === "tvc-project" && <TvcProjectPage id={route.id} />}
              </Page>
            </AnimatePresence>
          </main>
          <AnimatePresence>{route.page !== "home" && <AppDock key="dock" route={route} />}</AnimatePresence>
          <JobsDock />
          <Toaster theme="light" position="top-right" richColors closeButton />
        </JobsProvider>
      </TooltipProvider>
    </MotionConfig>
  )
}
