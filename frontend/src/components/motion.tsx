// 动效小工具：入场、依次出现、数字滚动
import { useEffect, useRef, type ReactNode } from "react"
import { animate, motion, useInView, useMotionValue, useTransform, type Variants } from "motion/react"

export const ease = [0.22, 1, 0.36, 1] as const

/** 整页切换：淡入 + 轻微上移 */
export function Page({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -6 }}
      transition={{ duration: 0.32, ease }}
    >
      {children}
    </motion.div>
  )
}

const container: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.045, delayChildren: 0.05 } },
}
export const item: Variants = {
  hidden: { opacity: 0, y: 14, scale: 0.985 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.42, ease } },
}

/** 子元素依次出现（子元素用 <StaggerItem>） */
export function Stagger({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={container} initial="hidden" animate="show">
      {children}
    </motion.div>
  )
}

export function StaggerItem({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={item}>
      {children}
    </motion.div>
  )
}

/** 数字从 0 滚动到目标值 */
export function CountUp({ value, decimals = 0, className }: { value: number; decimals?: number; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null)
  const inView = useInView(ref, { once: true })
  const mv = useMotionValue(0)
  const text = useTransform(mv, (v) => v.toFixed(decimals))
  useEffect(() => {
    if (!inView) return
    const c = animate(mv, value, { duration: 0.9, ease })
    return () => c.stop()
  }, [inView, value, mv])
  return <motion.span ref={ref} className={className}>{text}</motion.span>
}

/** 进度条：宽度从 0 长到目标 */
export function GrowBar({ value, className }: { value: number; className?: string }) {
  return (
    <motion.div
      className={className}
      initial={{ width: 0 }}
      animate={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
      transition={{ duration: 0.8, ease, delay: 0.15 }}
    />
  )
}
