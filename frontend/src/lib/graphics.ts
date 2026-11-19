export interface EditorFont {
  id: string; name: string; family: string; builtin: boolean; file: string; preview_scale: number
}
export type Animation = "none" | "fade" | "pop" | "pulse" | "bounce" | "shake"
export type Sticker = "arrow" | "circle" | "heart" | "sparkle" | "check" | "badge"
export interface TextStyle {
  font_id: string; enabled: boolean; size: number; x: number; y: number
  color: string; outline_color: string; outline: number; bold: boolean
}
export interface GraphicElement extends TextStyle {
  id: string; type: "text" | "sticker"; text: string; icon: Sticker; animation: Animation
  start: number; end: number | null; rotation: number; opacity: number
}
export interface GraphicsSettings { subtitle: TextStyle; elements: GraphicElement[] }
export const ANIMATIONS: [Animation, string][] = [["none", "静止"], ["fade", "淡入"], ["pop", "弹入"], ["pulse", "呼吸缩放"], ["bounce", "上下跳动"], ["shake", "轻轻摇摆"]]
export const STICKERS: [Sticker, string, string][] = [
  ["arrow", "引导箭头", "#FFE600"], ["circle", "重点圈选", "#FF4545"], ["heart", "点赞爱心", "#FF5078"],
  ["sparkle", "亮点闪光", "#FFE600"], ["check", "认证对勾", "#2CD995"], ["badge", "好价标签", "#FF6535"],
]
export const SHAPES: Record<Sticker, string> = {
  arrow: "M6 42 L62 42 62 22 96 50 62 78 62 58 6 58 Z",
  circle: "M50 4 C75 4 96 25 96 50 C96 75 75 96 50 96 C25 96 4 75 4 50 C4 25 25 4 50 4 Z M50 13 C30 13 13 30 13 50 C13 70 30 87 50 87 C70 87 87 70 87 50 C87 30 70 13 50 13 Z",
  heart: "M50 88 C43 80 6 58 6 31 C6 5 39 2 50 24 C61 2 94 5 94 31 C94 58 57 80 50 88 Z",
  sparkle: "M50 2 L63 37 98 50 63 63 50 98 37 63 2 50 37 37 Z",
  check: "M8 49 L22 35 42 55 79 15 94 29 43 84 Z",
  badge: "M10 20 L90 20 100 35 100 65 90 80 10 80 0 65 0 35 Z",
}
export function pose(animation: Animation, elapsed: number) {
  if (animation === "pulse") return [1 + .12 * Math.sin(elapsed * Math.PI * 2 / 1.2), 0, 0, 1]
  if (animation === "bounce") return [1, -.12 * (1 - Math.cos(elapsed * Math.PI * 2)), 0, 1]
  if (animation === "shake") return [1, 0, 10 * Math.sin(elapsed * Math.PI * 2 / .8), 1]
  if (animation === "pop") return [Math.min(1, .65 + elapsed / .35 * .35), 0, 0, Math.min(1, elapsed / .15)]
  if (animation === "fade") return [1, 0, 0, Math.min(1, elapsed / .4)]
  return [1, 0, 0, 1]
}
export function makeElement(style: TextStyle, type: "text" | "sticker", icon: Sticker = "arrow"): GraphicElement {
  return { ...style, id: crypto.randomUUID(), type, icon, enabled: true, text: type === "text" ? "点击修改文字" : icon === "badge" ? "好价" : "",
    size: type === "text" ? 110 : 220, x: 50, y: 30, color: type === "text" ? "#FFFFFF" : STICKERS.find(([key]) => key === icon)![2],
    outline: type === "text" ? 5 : 0, rotation: 0, opacity: 1, start: 0, end: type === "text" ? null : 3,
    animation: type === "text" ? "none" : icon === "arrow" ? "bounce" : "pulse" }
}
