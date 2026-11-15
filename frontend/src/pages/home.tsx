import { ArrowRight, Captions, ClipboardCheck, Clapperboard, Mic } from "lucide-react"
import { motion } from "motion/react"

import { ease, Stagger, StaggerItem } from "@/components/motion"

const STEPS = [
  { n: "01", icon: Mic, title: "语音识别", desc: "逐句标出粤语还是普通话，带时间戳" },
  { n: "02", icon: Captions, title: "出剪辑脚本", desc: "开头钩子 → 逐只表讲解 → 结尾引导" },
  { n: "03", icon: ClipboardCheck, title: "人工审核", desc: "改字幕、删句、调顺序、试听配音" },
  { n: "04", icon: Clapperboard, title: "出片", desc: "1440×2560 · 60fps · 字幕角标" },
]

export function HomePage() {
  return (
    <div className="relative min-h-[calc(100svh-3rem)] overflow-hidden">
      {/* 背景缓慢流动的光斑 */}
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="blob top-[8%] left-[12%] size-[340px] bg-[oklch(0.88_0.1_85)]" />
        <div className="blob top-[30%] right-[8%] size-[300px] bg-[oklch(0.86_0.07_250)]" style={{ animationDelay: "-6s" }} />
        <div className="blob bottom-[5%] left-[35%] size-[260px] bg-[oklch(0.9_0.06_160)]" style={{ animationDelay: "-12s" }} />
      </div>

      <div className="relative mx-auto max-w-3xl px-6 pt-[10vh] text-center">
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="text-xs tracking-[0.35em] text-gold-ink"
        >
          JUHANG STUDIO
        </motion.div>
        <motion.h1
          initial={{ opacity: 0, y: 14, filter: "blur(6px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          transition={{ duration: 0.6, ease, delay: 0.05 }}
          className="mt-3 text-4xl font-bold tracking-wide"
        >
          选一个拍摄批次开始
        </motion.h1>
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.2 }}
          className="mx-auto mt-4 max-w-xl leading-relaxed text-muted-foreground"
        >
          左边按拍摄日期列出素材文件夹。一键识别后，大模型按参考成片的结构出剪辑脚本，你审核确认后再出片。
        </motion.p>

        <Stagger className="mt-12 grid grid-cols-2 gap-3 text-left md:grid-cols-4">
          {STEPS.map((s, i) => (
            <StaggerItem key={s.n} className="relative">
              <div className="lift soft-shadow group h-full rounded-2xl border bg-card/90 p-4 backdrop-blur">
                <div className="flex items-center justify-between">
                  <span className="text-2xl font-bold text-gold-ink tabular">{s.n}</span>
                  <span className="grid size-8 place-items-center rounded-lg bg-primary/12 text-gold-ink transition-transform duration-300 group-hover:scale-110 group-hover:rotate-6">
                    <s.icon className="size-4" />
                  </span>
                </div>
                <div className="mt-3 font-semibold">{s.title}</div>
                <div className="mt-1 text-xs leading-relaxed text-muted-foreground">{s.desc}</div>
              </div>
              {i < STEPS.length - 1 && (
                <motion.span
                  className="absolute top-1/2 -right-2.5 z-10 hidden -translate-y-1/2 text-primary md:block"
                  animate={{ x: [0, 3, 0] }}
                  transition={{ duration: 1.8, repeat: Infinity, ease: "easeInOut", delay: i * 0.3 }}
                >
                  <ArrowRight className="size-4" />
                </motion.span>
              )}
            </StaggerItem>
          ))}
        </Stagger>
      </div>
    </div>
  )
}
