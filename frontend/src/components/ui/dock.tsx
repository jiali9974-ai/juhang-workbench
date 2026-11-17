// 底部 Dock 导航（改自 motion-primitives 的 Dock）：鼠标靠近时图标放大，悬停显示文字。
// 和原版的区别：用 motion/react；DockItem 可以点（onClick / 回车 / 空格）、可标记当前页；
// 只把 width / isHovered 传给 DockLabel、DockIcon，其他子元素原样渲染。
import {
  AnimatePresence,
  motion,
  useMotionValue,
  useSpring,
  useTransform,
  type MotionValue,
  type SpringOptions,
} from "motion/react"
import {
  Children,
  cloneElement,
  createContext,
  isValidElement,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react"

import { cn } from "@/lib/utils"

const DOCK_HEIGHT = 128
const DEFAULT_MAGNIFICATION = 80
const DEFAULT_DISTANCE = 150
const DEFAULT_PANEL_HEIGHT = 64

type DockProps = {
  children: ReactNode
  className?: string
  distance?: number
  panelHeight?: number
  magnification?: number
  spring?: SpringOptions
}
type DockItemProps = {
  className?: string
  children: ReactNode
  onClick?: () => void
  /** 读屏和键盘用的名字 */
  label?: string
  /** 当前所在页面 */
  active?: boolean
}
type DockLabelProps = { className?: string; children: ReactNode }
type DockIconProps = { className?: string; children: ReactNode }

type DockContextType = {
  mouseX: MotionValue<number>
  spring: SpringOptions
  magnification: number
  distance: number
}

const DockContext = createContext<DockContextType | undefined>(undefined)

function useDock() {
  const context = useContext(DockContext)
  if (!context) throw new Error("useDock 必须放在 <Dock> 里面")
  return context
}

function Dock({
  children,
  className,
  spring = { mass: 0.1, stiffness: 150, damping: 12 },
  magnification = DEFAULT_MAGNIFICATION,
  distance = DEFAULT_DISTANCE,
  panelHeight = DEFAULT_PANEL_HEIGHT,
}: DockProps) {
  const mouseX = useMotionValue(Infinity)
  const isHovered = useMotionValue(0)

  const maxHeight = useMemo(() => Math.max(DOCK_HEIGHT, magnification + magnification / 2 + 4), [magnification])
  const heightRow = useTransform(isHovered, [0, 1], [panelHeight, maxHeight])
  const height = useSpring(heightRow, spring)

  return (
    <motion.div style={{ height, scrollbarWidth: "none" }} className="mx-2 flex max-w-full items-end overflow-x-auto">
      <motion.div
        onMouseMove={({ clientX }) => {
          isHovered.set(1)
          mouseX.set(clientX)
        }}
        onMouseLeave={() => {
          isHovered.set(0)
          mouseX.set(Infinity)
        }}
        className={cn("mx-auto flex w-fit gap-4 rounded-2xl bg-gray-50 px-4", className)}
        style={{ height: panelHeight }}
        role="toolbar"
        aria-label="主导航"
      >
        <DockContext.Provider value={{ mouseX, spring, distance, magnification }}>{children}</DockContext.Provider>
      </motion.div>
    </motion.div>
  )
}

function DockItem({ children, className, onClick, label, active }: DockItemProps) {
  const ref = useRef<HTMLDivElement>(null)
  const { distance, magnification, mouseX, spring } = useDock()
  const isHovered = useMotionValue(0)

  const mouseDistance = useTransform(mouseX, (val) => {
    const domRect = ref.current?.getBoundingClientRect() ?? { x: 0, width: 0 }
    return val - domRect.x - domRect.width / 2
  })
  const widthTransform = useTransform(mouseDistance, [-distance, 0, distance], [40, magnification, 40])
  const width = useSpring(widthTransform, spring)

  return (
    <motion.div
      ref={ref}
      style={{ width }}
      onHoverStart={() => isHovered.set(1)}
      onHoverEnd={() => isHovered.set(0)}
      onFocus={() => isHovered.set(1)}
      onBlur={() => isHovered.set(0)}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          onClick?.()
        }
      }}
      className={cn("relative inline-flex items-center justify-center outline-none focus-visible:ring-2 focus-visible:ring-foreground/40", className)}
      tabIndex={0}
      role="button"
      aria-label={label}
      aria-current={active ? "page" : undefined}
    >
      {Children.map(children, (child) =>
        isValidElement(child) && (child.type === DockLabel || child.type === DockIcon)
          ? cloneElement(child as ReactElement<Record<string, unknown>>, { width, isHovered })
          : child,
      )}
    </motion.div>
  )
}

function DockLabel({ children, className, ...rest }: DockLabelProps) {
  const isHovered = (rest as Record<string, unknown>).isHovered as MotionValue<number>
  const [isVisible, setIsVisible] = useState(false)

  useEffect(() => {
    const unsubscribe = isHovered.on("change", (latest) => setIsVisible(latest === 1))
    return () => unsubscribe()
  }, [isHovered])

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ opacity: 0, y: 0 }}
          animate={{ opacity: 1, y: -10 }}
          exit={{ opacity: 0, y: 0 }}
          transition={{ duration: 0.2 }}
          className={cn(
            "absolute -top-6 left-1/2 w-fit rounded-md border border-gray-200 bg-gray-100 px-2 py-0.5 text-xs whitespace-pre text-neutral-700",
            className,
          )}
          role="tooltip"
          style={{ x: "-50%" }}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function DockIcon({ children, className, ...rest }: DockIconProps) {
  const width = (rest as Record<string, unknown>).width as MotionValue<number>
  const widthTransform = useTransform(width, (val) => val / 2)
  return (
    <motion.div style={{ width: widthTransform }} className={cn("flex items-center justify-center", className)}>
      {children}
    </motion.div>
  )
}

export { Dock, DockIcon, DockItem, DockLabel }
