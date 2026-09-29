import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'

/**
 * 离线预览构建 —— 产出一个可以双击直接打开的单文件 HTML。
 *
 * 与常规构建（vite.config.ts）的三点差异，都是为了 file:// 协议：
 * 1. base './' —— 资源用相对路径，脱离服务器也能找到；
 * 2. format 'iife' —— 浏览器在 file:// 下禁止加载 ES module（CORS 限制），
 *    必须打成传统脚本；
 * 3. assetsInlineLimit 调到极大 —— 图片、字体全部内联成 data URI，
 *    配合 build:inline-offline.mjs 把 JS/CSS 也塞进 HTML，最终只剩一个文件。
 */
export default defineConfig({
  plugins: [react()],
  base: './',
  define: {
    // 离线文件里「机构量化研报模式」按钮要指向线上旧看板，
    // 否则会跳去 file:/// 打开一片空白。放在配置里而不是 npm 脚本里，避免依赖 shell 的
    // 环境变量语法（Windows 下 `FOO=bar cmd` 不成立）。
    'import.meta.env.VITE_LEGACY_HOME_URL': JSON.stringify(
      'https://yuxuanwucn.github.io/stock-dashboard/',
    ),
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: 'dist-offline',
    emptyOutDir: true,
    assetsInlineLimit: 100 * 1024 * 1024,
    cssCodeSplit: false,
    modulePreload: false,
    rollupOptions: {
      output: {
        format: 'iife',
        inlineDynamicImports: true,
      },
    },
  },
})
