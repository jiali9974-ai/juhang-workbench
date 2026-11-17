import { Fragment } from "react"
import { ChevronRight } from "lucide-react"

import { SidebarTrigger } from "@/components/ui/sidebar"
import { Separator } from "@/components/ui/separator"
import { href, type Route } from "@/hooks/use-route"

export function TopBar({ route }: { route: Route }) {
  const crumbs: { label: string; to?: string }[] = [{ label: "工作台", to: href({ page: "home" }) }]
  if (route.page === "batch" || route.page === "script") {
    crumbs.push({ label: `批次 ${route.batch}`, to: href({ page: "batch", batch: route.batch, tab: "scripts" }) })
    if (route.page === "batch" && route.tab === "clips") crumbs.push({ label: "素材库" })
    if (route.page === "script") crumbs.push({ label: `审核 ${route.id}` })
  }
  return (
    <header className="sticky top-0 z-20 flex h-12 shrink-0 items-center gap-2 border-b bg-background/80 px-4 backdrop-blur">
      <SidebarTrigger className="-ml-1 text-muted-foreground" />
      <Separator orientation="vertical" className="mr-1 data-[orientation=vertical]:h-4" />
      <nav className="flex min-w-0 items-center gap-1.5 text-sm">
        {crumbs.map((c, i) => (
          <Fragment key={i}>
            {i > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground/60" />}
            {c.to && i < crumbs.length - 1 ? (
              <a href={c.to} className="truncate text-muted-foreground hover:text-foreground">{c.label}</a>
            ) : (
              <span className="truncate font-medium">{c.label}</span>
            )}
          </Fragment>
        ))}
      </nav>
    </header>
  )
}
