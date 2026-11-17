import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// 开发时 /api 转发到本机工作台服务（JH_API 可以换成别的端口，比如测试用的第二个工作台）；打包后由 FastAPI 直接提供页面
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { port: 5173, proxy: { "/api": process.env.JH_API || "http://127.0.0.1:8765" } },
})
