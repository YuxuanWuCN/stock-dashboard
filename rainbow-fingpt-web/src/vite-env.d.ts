/// <reference types="vite/client" />

/**
 * Vite 环境变量类型声明。
 *
 * `vite/client` 只声明了 DEV / PROD / MODE / BASE_URL 等内置变量，
 * 自定义的 VITE_* 变量必须在这里补声明，否则 `import.meta.env.VITE_*`
 * 在 `tsc -b`（strict 模式）下会报「Property does not exist」。
 */
interface ImportMetaEnv {
  /** 后端 API 基地址（首选变量名）；留空表示同源（生产环境由 Flask 托管时用相对路径） */
  readonly VITE_API_BASE_URL?: string
  /** 后端 API 基地址（上一版遗留变量名，仍兼容） */
  readonly VITE_API_BASE?: string
  /** 旧版看板地址，「机构量化研报模式」按钮点击后跳转到这里 */
  readonly VITE_LEGACY_HOME_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
