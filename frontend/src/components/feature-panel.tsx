// 左边文字列表、右边视频/图片的版式（参考 21st.dev 的 FeaturesWithPanel）。
// 点左边一项，右边换成它的视频或图片；窄屏时视频直接展开在那一项下面。
import type { ReactNode } from "react"
import { AnimatePresence, motion } from "motion/react"

import { cn } from "@/lib/utils"

export interface PanelItem {
  key: string
  title: ReactNode
  /** 标题右边的小状态 */
  badge?: ReactNode
  /** 选中后展开的说明和按钮 */
  detail?: ReactNode
  /** 右边显示的视频或图片 */
  media: ReactNode
}

const smooth = [0.4, 0, 0.2, 1] as const

/** 竖屏 9:16 的画框：高度不超过一屏，留出顶部和底部导航的位置 */
export function MediaFrame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn("relative mx-auto aspect-[9/16] w-full overflow-hidden rounded-2xl bg-muted ring-1 ring-foreground/10", className)}
      style={{ maxWidth: "min(100%, calc((100svh - 13rem) * 9 / 16))" }}
    >
      {children}
    </div>
  )
}

export function MediaVideo({ src, poster }: { src: string; poster?: string }) {
  return <video key={src} src={src} poster={poster} autoPlay muted loop playsInline controls className="size-full bg-black object-contain" />
}

export function MediaImage({ src, alt = "" }: { src: string; alt?: string }) {
  return <img src={src} alt={alt} draggable={false} className="size-full object-cover" />
}

/** 一组素材缩略图拼成 3×3（还没有成片时右边显示这个） */
export function MediaMosaic({ srcs, children }: { srcs: string[]; children?: ReactNode }) {
  const cells = srcs.slice(0, 9)
  return (
    <div className="relative size-full">
      <div className="grid size-full grid-cols-3 grid-rows-3 gap-0.5 bg-background">
        {cells.map((s, i) => (
          <motion.img
            key={s}
            src={s}
            alt=""
            loading="lazy"
            draggable={false}
            initial={{ opacity: 0, scale: 1.04 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, delay: i * 0.04 }}
            className="size-full bg-muted object-cover"
          />
        ))}
        {Array.from({ length: Math.max(0, 9 - cells.length) }, (_, i) => <span key={`e${i}`} className="bg-muted" />)}
      </div>
      {children}
    </div>
  )
}

export function FeaturePanel({ header, items, active, onActive, empty, aside, footer }: {
  header: ReactNode
  items: PanelItem[]
  active: number
  onActive: (i: number) => void
  /** 没有条目时左边显示的内容 */
  empty?: ReactNode
  /** 不用条目的媒体，右边固定显示这个 */
  aside?: ReactNode
  /** 放在左侧列表下方的附加内容，例如创建项目的上传框。 */
  footer?: ReactNode
}) {
  const cur = items[Math.min(active, items.length - 1)]
  const right = aside ?? cur?.media
  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-2 lg:items-stretch lg:gap-16">
      <div className="flex min-h-0 min-w-0 flex-col">
        <div className="shrink-0">{header}</div>
        <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-2xl border bg-card">
          <div className="flex shrink-0 items-center justify-between border-b px-4 py-3 text-sm">
            <span className="font-medium">全部项目</span>
            <span className="text-xs text-muted-foreground tabular">{items.length} 个项目</span>
          </div>
          <div role="region" aria-label="素材项目列表" tabIndex={0} className="scroll-region min-h-0 flex-1 p-2">
            {items.length === 0 ? empty : (
              <ul className="flex flex-col gap-1 p-0.5">
                {items.map((item, index) => {
                  const on = cur?.key === item.key
                  return (
                    <motion.li
                      key={item.key}
                      initial={{ opacity: 0, y: 8 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.35, delay: Math.min(index, 12) * 0.05, ease: "easeOut" }}
                      onClick={() => onActive(index)}
                      className={cn(
                        "flex cursor-pointer flex-col rounded-xl px-4 py-3.5 transition-all duration-200",
                        on ? "ring-1 ring-foreground" : "ring-1 ring-transparent hover:bg-muted/60",
                      )}
                    >
                      <div className="flex w-full items-center gap-4">
                        <span
                          className={cn(
                            "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-medium tabular transition-colors duration-200",
                            on ? "bg-foreground text-background" : "bg-muted text-muted-foreground",
                          )}
                        >
                          {index + 1}
                        </span>
                        <span title={typeof item.title === "string" ? item.title : undefined} className={cn("min-w-0 flex-1 truncate text-sm font-medium transition-colors duration-200", on ? "text-foreground" : "text-muted-foreground")}>
                          {item.title}
                        </span>
                        {item.badge}
                      </div>

                      <AnimatePresence initial={false}>
                        {on && (
                          <motion.div
                            initial={{ height: 0, opacity: 0 }}
                            animate={{ height: "auto", opacity: 1 }}
                            exit={{ height: 0, opacity: 0 }}
                            transition={{ duration: 0.35, ease: smooth }}
                            className="w-full overflow-hidden"
                          >
                            {item.detail && <div className="pt-2.5 pl-11">{item.detail}</div>}
                            {!aside && (
                              <div className="mt-3 lg:hidden">
                                <MediaFrame>{item.media}</MediaFrame>
                              </div>
                            )}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.li>
                  )
                })}
              </ul>
            )}
          </div>
        </section>
        {footer && <div className="shrink-0 pt-4">{footer}</div>}
      </div>

      <div className={cn("min-h-0", !aside && "hidden lg:block", !aside && !cur && "lg:hidden")}>
        <MediaFrame>
          <AnimatePresence mode="wait">
            <motion.div
              key={aside ? "aside" : cur?.key ?? "none"}
              initial={{ opacity: 0, y: 12, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.35, ease: smooth }}
              className="absolute inset-0"
            >
              {right}
            </motion.div>
          </AnimatePresence>
        </MediaFrame>
      </div>
    </div>
  )
}
