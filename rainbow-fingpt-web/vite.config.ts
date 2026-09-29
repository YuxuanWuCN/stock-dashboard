import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig(({ command }) => ({
  plugins: [react()],
  /**
   * 新首页由 Flask 后端托管在 /home/ 下（src/server.py 的 /home 路由读取 docs/home/）。
   * 构建产物的资源路径必须带 /home/ 前缀，否则部署后会 404；
   * 开发服务器仍挂在根路径，方便 npm run dev 直接访问 http://localhost:5173。
   */
  base: command === 'build' ? '/home/' : '/',
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: { port: 5173, open: true },
}))
