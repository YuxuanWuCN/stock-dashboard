import type {
  ApiError as ApiErrorBody,
  DatasetMeta,
  DatasetRow,
  GetHomepageQuery,
  GetHomepageResponse,
  ListDatasetQuery,
  ListDatasetResponse,
  ProcessDatasetRequest,
  ProcessDatasetResponse,
} from '@/types/api'

/**
 * 后端 API 客户端。
 *
 * 用原生 fetch 实现（项目没有引入 axios；如果要换 axios，只需替换本文件底部的
 * request 实现，下面 4 个接口函数与类型都不用动）。
 *
 * 基地址解析优先级：
 *   1. `VITE_API_BASE_URL`（推荐，写在 .env.local）
 *   2. `VITE_API_BASE`（上一版遗留名，保留兼容）
 *   3. 开发环境 → http://127.0.0.1:5000；生产环境 → 同源（空字符串）
 *
 * ⚠️ 注意端口：本项目后端是 **Flask，跑在 5000**（`python src/server.py`，
 * 双进程模式为 5001）。FastAPI/Express 常见的 8000 是本项目没有用到的端口。
 */
const DEFAULT_DEV_BASE = 'http://127.0.0.1:5000'

export const API_BASE_URL = (
  import.meta.env.VITE_API_BASE_URL ??
  import.meta.env.VITE_API_BASE ??
  (import.meta.env.DEV ? DEFAULT_DEV_BASE : '')
).replace(/\/+$/, '')

/**
 * 「机构量化研报模式」按钮跳转的旧版看板地址。
 * 生产环境旧看板挂在站点根路径 `/`；开发时前端在 5173、旧看板在后端 5000。
 */
export const LEGACY_HOME_URL =
  import.meta.env.VITE_LEGACY_HOME_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:5000/' : '/')

const DEFAULT_TIMEOUT_MS = 10_000

/** 运行时错误：携带 HTTP 状态码与后端返回的 detail。 */
export class ApiError extends Error {
  readonly status: number
  readonly detail?: string

  constructor(message: string, status = 0, detail?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

export type QueryValue = string | number | boolean | null | undefined
export type QueryParams = Record<string, QueryValue | QueryValue[]>

/**
 * 序列化查询参数。
 *
 * 数组按 OpenAPI 的 `style=form & explode=false` 规则拼成逗号分隔
 * （与后端 `type=stock,etf`、`risk_level=low,medium` 的多值约定一致）。
 * 空字符串 / null / undefined 会被跳过；`false` 与 `0` 是有效值，照常发送。
 */
export function buildQuery(params?: object): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, raw] of Object.entries(params)) {
    const value = raw as QueryValue | QueryValue[]
    if (Array.isArray(value)) {
      const joined = value.filter((v) => v !== undefined && v !== null && v !== '').join(',')
      if (joined) search.append(key, joined)
      continue
    }
    if (value === undefined || value === null || value === '') continue
    search.append(key, String(value))
  }
  const query = search.toString()
  return query ? `?${query}` : ''
}

export interface CallOptions {
  /** 外部中断信号（组件卸载时取消请求） */
  signal?: AbortSignal
  /** 超时时间，默认 10s */
  timeoutMs?: number
}

interface RequestOptions extends CallOptions {
  method?: 'GET' | 'POST'
  query?: object
  body?: unknown
}

/** 统一请求入口：拼 query、超时、解析错误体。 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', query, body, timeoutMs = DEFAULT_TIMEOUT_MS, signal } = options

  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), timeoutMs)
  const forwardAbort = () => controller.abort()
  signal?.addEventListener('abort', forwardAbort)

  try {
    const response = await fetch(`${API_BASE_URL}${path}${buildQuery(query)}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) throw await toApiError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    const reason = error as Error | undefined
    if (reason?.name === 'AbortError') {
      throw new ApiError(signal?.aborted ? '请求已取消' : '请求超时，请稍后重试', 0)
    }
    throw new ApiError(reason?.message ?? '网络异常，请检查后端是否已启动', 0)
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', forwardAbort)
  }
}

/** 把后端的 `{ error, detail }` 错误体转成 ApiError。 */
async function toApiError(response: Response): Promise<ApiError> {
  let message = `HTTP ${response.status}`
  let detail: string | undefined
  try {
    const payload = (await response.json()) as Partial<ApiErrorBody>
    if (typeof payload?.error === 'string') message = payload.error
    if (typeof payload?.detail === 'string') detail = payload.detail
  } catch {
    // 错误体不是 JSON（网关超时、HTML 错误页等），保留 HTTP 状态文案
  }
  return new ApiError(message, response.status, detail)
}

/* ------------------------------------------------------------------ 接口封装 */

/** 数据集分页响应：`items` 的元素类型随是否传 `fields` 变化。 */
export interface DatasetPage<T> {
  meta: DatasetMeta
  items: T[]
}

/** 传了 `fields` 时，返回项是稀疏对象：只有被选中的字段存在。 */
export type SparseDatasetRow = Partial<DatasetRow>

/**
 * GET /api/v1/dataset —— 分页查询数据集。
 *
 * 传 `fields` 做字段裁剪时，响应项是稀疏对象，重载会自动把返回类型收窄成
 * `Partial<DatasetRow>[]`，避免"类型检查通过、运行时却是 undefined"。
 *
 * @example
 * // 全字段（类型安全，item 上有所有字段）
 * const page = await fetchDataset({ type: ['stock'], sort: '-total_score', page_size: 20 })
 * page.items[0].scores.total
 *
 * // 稀疏字段（返回 Partial<DatasetRow>）
 * const slim = await fetchDataset({ fields: ['code', 'name'] })
 * slim.items[0].name      // ✅
 * slim.items[0].scores    // ❌ 类型报错，因为没在 fields 里
 */
export function fetchDataset(
  query: ListDatasetQuery & { fields: string[] },
  options?: CallOptions,
): Promise<DatasetPage<SparseDatasetRow>>
export function fetchDataset(
  query?: ListDatasetQuery,
  options?: CallOptions,
): Promise<ListDatasetResponse>
export function fetchDataset(
  query: ListDatasetQuery = {},
  options: CallOptions = {},
): Promise<ListDatasetResponse | DatasetPage<SparseDatasetRow>> {
  return request<ListDatasetResponse | DatasetPage<SparseDatasetRow>>('/api/v1/dataset', {
    query,
    ...options,
  })
}

/**
 * POST /api/v1/process —— 提交处理请求：选股 / 组合权重 / 聚合统计。
 *
 * @example
 * const result = await processData({
 *   operation: 'allocate',
 *   filters: { risk_level: ['low', 'medium'], min_score: 30 },
 *   top_n: 10,
 *   weighting: 'risk_inverse',
 *   max_weight: 0.25,
 * })
 */
export function processData(
  body: ProcessDatasetRequest,
  options: CallOptions = {},
): Promise<ProcessDatasetResponse> {
  return request<ProcessDatasetResponse>('/api/v1/process', { method: 'POST', body, ...options })
}

/** 与 processData 等价，供按「提交数据」语义命名的调用方使用。 */
export const submitData = processData

/**
 * GET /api/v1/homepage —— 首页视图模型（一次请求渲染整页）。
 */
export function fetchHomepage(
  query: GetHomepageQuery = {},
  options: CallOptions = {},
): Promise<GetHomepageResponse> {
  return request<GetHomepageResponse>('/api/v1/homepage', { query, ...options })
}

/** GET /api/v1/openapi.json —— 拉取 OpenAPI 3.0 规格本身。 */
export function fetchOpenApiSpec(options: CallOptions = {}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>('/api/v1/openapi.json', options)
}

/** 方便按需调用：全部接口函数的集合。 */
export const api = {
  fetchDataset,
  processData,
  submitData,
  fetchHomepage,
  fetchOpenApiSpec,
}
