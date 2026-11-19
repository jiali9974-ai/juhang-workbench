import { useRef, type PointerEvent } from "react"
import { SHAPES, pose, type EditorFont, type GraphicElement, type GraphicsSettings, type TextStyle } from "@/lib/graphics"

type Layer = GraphicElement | (TextStyle & { id: "subtitle"; type: "text"; text: string })

export function StickerShape({ icon, color }: { icon: GraphicElement["icon"]; color: string }) {
  return <svg viewBox="0 0 100 100" className="size-full" aria-hidden="true"><path d={SHAPES[icon]} fill={color} /></svg>
}

export function GraphicsCanvas({ settings, fonts, selected, onSelect, onMove, time, editing = true }: {
  settings: GraphicsSettings; fonts: EditorFont[]; selected: string; onSelect: (id: string) => void
  onMove: (id: string, x: number, y: number) => void; time: number; editing?: boolean
}) {
  const canvas = useRef<HTMLDivElement>(null)
  const drag = useRef<{ id: string; x: number; y: number; px: number; py: number } | null>(null)
  const layers: Layer[] = [{ ...settings.subtitle, id: "subtitle", type: "text", text: "这是口播字幕预览" }, ...settings.elements]
  function start(event: PointerEvent<HTMLButtonElement>, layer: Layer) {
    event.stopPropagation()
    if (!editing) return
    onSelect(layer.id)
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = { id: layer.id, x: layer.x, y: layer.y, px: event.clientX, py: event.clientY }
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current, bounds = canvas.current?.getBoundingClientRect()
    if (!current || !bounds) return
    onMove(current.id, Math.max(0, Math.min(100, current.x + (event.clientX - current.px) / bounds.width * 100)),
      Math.max(0, Math.min(100, current.y + (event.clientY - current.py) / bounds.height * 100)))
  }
  return (
    <div ref={canvas} className="absolute inset-0" style={{ containerType: "inline-size" }} aria-label="画面元素预览">
      {editing && <div className="pointer-events-none absolute inset-x-[5%] inset-y-[5%] rounded-sm border border-dashed border-white/20" />}
      {layers.map((layer) => {
        const element = layer.id === "subtitle" ? null : layer as GraphicElement
        if (!layer.enabled || (element && (time < element.start || (element.end !== null && time >= element.end)))) return null
        const [scale, dy, angle, alpha] = element ? pose(element.animation, Math.max(0, time - element.start)) : [1, 0, 0, 1]
        const font = fonts.find((font) => font.id === layer.font_id)
        const isSticker = element?.type === "sticker"
        const textSize = isSticker ? layer.size * .26 : layer.size
        return (
          <button key={layer.id} type="button" aria-label={`选择${layer.id === "subtitle" ? "口播字幕" : element?.type === "sticker" ? "标识" : "文字"}：${layer.text || (element?.type === "sticker" ? element.icon : "未命名文字")}`}
            onPointerDown={(event) => start(event, layer)} onPointerMove={move} onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}
            onClick={() => onSelect(layer.id)} onKeyDown={(event) => {
              if (!editing || !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return
              event.preventDefault(); onMove(layer.id, Math.max(0, Math.min(100, layer.x + (event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0))),
                Math.max(0, Math.min(100, layer.y + (event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0))))
            }}
            className="absolute touch-none select-none border-0 bg-transparent p-0 leading-none outline-none"
            style={{ left: `${layer.x}%`, top: `calc(${layer.y}% + ${dy * layer.size / 1440 * 100}cqw)`,
              transform: `translate(-50%, -50%) rotate(${-((element?.rotation ?? 0) + angle)}deg) scale(${scale})`,
              opacity: alpha * (element?.opacity ?? 1), cursor: editing ? "move" : "default", maxWidth: "none" }}>
            <span className={`relative block ${editing && selected === layer.id ? "outline-2 outline-offset-4 outline-white" : ""}`}
              style={isSticker ? { width: `${layer.size / 1440 * 100}cqw`, height: `${layer.size / 1440 * 100}cqw` } : undefined}>
              {isSticker && <StickerShape icon={element.icon} color={layer.color} />}
              {(!isSticker || element.icon === "badge") && <span className={isSticker ? "absolute inset-0 grid place-items-center" : "block whitespace-pre"}
                style={{ fontFamily: `"jh-${layer.font_id}", "jh-SourceHanSansCN-Heavy", sans-serif`, fontSize: `${textSize / 1440 * 100 * (font?.preview_scale ?? .7)}cqw`,
                  fontWeight: layer.bold ? 700 : 400, lineHeight: 1 / (font?.preview_scale ?? .7), color: isSticker ? "white" : layer.color,
                  WebkitTextStroke: isSticker ? undefined : `${layer.outline / 1440 * 100}cqw ${layer.outline_color}`, paintOrder: "stroke fill" }}>
                {layer.text || (isSticker ? "好价" : editing ? "输入文字" : "")}
              </span>}
            </span>
          </button>
        )
      })}
    </div>
  )
}
