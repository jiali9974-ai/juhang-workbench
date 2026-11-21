import { AnimatePresence, MotionConfig } from "motion/react"

import { AppDock } from "@/components/app-dock"
import { JobsDock } from "@/components/jobs-dock"
import { Page } from "@/components/motion"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { JobsProvider } from "@/hooks/use-jobs"
import { href, useRoute } from "@/hooks/use-route"
import { BatchPage } from "@/pages/batch-page"
import { BeautyPage } from "@/pages/beauty-page"
import { FlowPage } from "@/pages/flow-page"
import { GenPage } from "@/pages/gen-page"
import { ProjectsPage } from "@/pages/projects-page"
import { ScriptEditor } from "@/pages/script-editor"
import { StartPage } from "@/pages/start-page"

// 布局：首页只有上传框；开始生成之后的页面底部都有居中的导航（生成 / 项目 / 美颜设置 / 流程图）。
// 以前的左侧边栏（components/app-sidebar.tsx）和顶栏不再使用。
export default function App() {
  const route = useRoute()
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
                {route.page === "gen" && <GenPage />}
                {route.page === "projects" && <ProjectsPage />}
                {route.page === "beauty" && <BeautyPage batch={route.batch} />}
                {route.page === "flow" && <FlowPage batch={route.batch} jobId={route.job} />}
                {route.page === "batch" && <BatchPage batch={route.batch} tab={route.tab} />}
                {route.page === "script" && <ScriptEditor batch={route.batch} id={route.id} />}
              </Page>
            </AnimatePresence>
          </main>
          <AnimatePresence>{route.page !== "home" && <AppDock key="dock" route={route} />}</AnimatePresence>
          <JobsDock hideCompleted={route.page === "gen"} hasNavigation={route.page !== "home"} />
          <Toaster theme="light" position="top-right" richColors closeButton />
        </JobsProvider>
      </TooltipProvider>
    </MotionConfig>
  )
}
