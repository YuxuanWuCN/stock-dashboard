import { fileURLToPath } from 'node:url'

/**
 * content 里的通配符默认相对 process.cwd() 解析。
 * 如果 dev/preview 不是从工程根目录启动（launchd、IDE 守护进程等），
 * 就会扫不到任何文件 → 一个工具类都不生成 → 页面塌成单列。
 * 这里改成相对配置文件自身定位，任何 cwd 都稳定。
 */
const root = fileURLToPath(new URL('.', import.meta.url))

/** @type {import('tailwindcss').Config} */
export default {
  content: [`${root}index.html`, `${root}src/**/*.{ts,tsx}`],
  theme: {
    extend: {
      /**
       * desk = 设计稿原始画布宽度。
       * 设计稿是 1214 宽的定稿稿，1178 内容 + 两侧 18 边距；用默认的 xl(1280) 会导致
       * 在 1214 宽的屏幕上拿不到并排布局，因此单开一档。
       */
      screens: { desk: '1214px' },
      colors: {
        page: '#F9FBFD',
        ink: {
          900: '#16243C',
          800: '#29394F',
          700: '#43536B',
          600: '#5A6675',
          500: '#7B8798',
          400: '#98A2B2',
          300: '#B6BEC9',
        },
        line: { DEFAULT: '#EDF1F5', strong: '#E4E9EF' },
        brand: { DEFAULT: '#26A17F', 600: '#1E8A6B', 50: '#E8F6F1' },
        gold: { DEFAULT: '#F08634', line: '#E9A93B', 50: '#FDF3E9' },
        risk: { DEFAULT: '#F0515A', 50: '#FEEBEC' },
        tech: { DEFAULT: '#3D87E8', 600: '#2F6FCE', 50: '#F5F9FE' },
        chip: '#F7FAFC',
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Noto Sans SC"', 'system-ui', 'sans-serif'],
      },
      maxWidth: { page: '1214px', shell: '1178px' },
      borderRadius: { card: '16px', chip: '12px', hero: '16px' },
      boxShadow: {
        card: '0 2px 10px rgba(22,36,60,.06)',
        float: '0 4px 18px rgba(22,36,60,.08)',
      },
      gridTemplateColumns: {
        main: '759px 401px',
        rail: '1.9fr 1fr',
        expert: '380px 406px 1fr',
      },
    },
  },
  plugins: [],
}
