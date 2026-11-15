import { AnimatePresence, MotionConfig } from "motion/react"

import { AppSidebar } from "@/components/app-sidebar"
import { JobsDock } from "@/components/jobs-dock"
import { Page } from "@/components/motion"
import { TopBar } from "@/components/top-bar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { Toaster } from "@/components/ui/sonner"
import { TooltipProvider } from "@/components/ui/tooltip"
import { JobsProvider } from "@/hooks/use-jobs"
import { href, useRoute } from "@/hooks/use-route"
import { BatchPage } from "@/pages/batch-page"
import { HomePage } from "@/pages/home"
import { ScriptEditor } from "@/pages/script-editor"
import { TvcHome } from "@/pages/tvc-home"
import { TvcProjectPage } from "@/pages/tvc-project"

export default function App() {
  const route = useRoute()
  // 批次页切换标签不算换页，不播放整页动画
  const pageKey = route.page === "batch" ? `batch/${route.batch}` : href(route)
  return (
    <MotionConfig reducedMotion="user">
      <TooltipProvider delayDuration={200}>
        <JobsProvider>
          <SidebarProvider>
            <AppSidebar route={route} />
            <SidebarInset className="min-h-svh">
              <TopBar route={route} />
              <AnimatePresence mode="wait" initial={false}>
                <Page key={pageKey}>
                  {route.page === "home" && <HomePage />}
                  {route.page === "batch" && <BatchPage batch={route.batch} tab={route.tab} />}
                  {route.page === "script" && <ScriptEditor batch={route.batch} id={route.id} />}
                  {route.page === "tvc" && <TvcHome />}
                  {route.page === "tvc-project" && <TvcProjectPage id={route.id} />}
                </Page>
              </AnimatePresence>
            </SidebarInset>
            <JobsDock />
            <Toaster theme="light" position="top-right" richColors closeButton />
          </SidebarProvider>
        </JobsProvider>
      </TooltipProvider>
    </MotionConfig>
  )
}
