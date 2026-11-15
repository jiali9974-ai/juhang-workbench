import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// 开发时 /api 转发到本机工作台服务；打包后由 FastAPI 直接提供页面
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
})
