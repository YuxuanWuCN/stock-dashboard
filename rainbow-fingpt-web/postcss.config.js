import { fileURLToPath } from 'node:url'

/**
 * 显式给出 Tailwind 配置的绝对路径。
 * 默认行为是按 process.cwd() 去找 tailwind.config.js —— 从别的目录启动 dev/preview
 * （例如用 launchd / 守护进程拉起）时 cwd 不是工程根目录，就会退化成默认配置，
 * 于是 `@apply bg-page` 这类自定义令牌全部报 “class does not exist”。
 */
export default {
  plugins: {
    tailwindcss: { config: fileURLToPath(new URL('./tailwind.config.js', import.meta.url)) },
    autoprefixer: {},
  },
}
