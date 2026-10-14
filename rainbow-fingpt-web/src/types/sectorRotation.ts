/** 板块轮动（GET /api/sector_rotation）视图模型
 *
 * 字段与后端 `docs/data/sector_rotation/latest_rotation.json` 一一对应。
 * 数据诚实性：`sentiment_source` 区分真实 LLM 情绪与价格宽度代理，
 * `strategy_validated=false` 表示尚未通过回测覆盖门槛，仅作决策参考。
 */

export type SectorRotationStatus = 'ok' | 'stale' | 'missing' | 'error'

/** 情绪来源标注（禁止把代理显示为 LLM 情绪） */
export type SentimentSource = 'llm_news_replay' | 'price_breadth_proxy' | 'fixture_only' | 'unknown'

export interface SectorRotationStateView {
  sector: string
  /** 板块中文名，例如 存储芯片 */
  name: string
  sentiment_score: number
  sentiment_trend: 'rising' | 'stable' | 'declining'
  volatility: number
  stock_count: number
  confidence: number
}

export interface SectorRotationLLMValidation {
  status?: 'agreed' | 'diverged' | 'unavailable'
  llm_should_rotate?: boolean
  llm_target_sector?: string | null
  llm_reason?: string
  llm_confidence?: number | null
}

export interface SectorRotationDecision {
  should_rotate: boolean
  current_sector: string
  target_sector: string | null
  reason: string
  confidence: number
  is_fallback: boolean
  llm_rationale: string | null
  llm_validation: SectorRotationLLMValidation | null
  execution_time_ms: number
  timestamp: string
}

export interface SectorRotationPortfolioState {
  current_sector: string
  holding_days: number
  monthly_rotations: number
  days_since_last_rotation: number
}

export interface SectorRotationPayload {
  schema_version: string
  generated_at: string
  trade_date: string
  sentiment_source: SentimentSource | string
  report_usable: boolean
  strategy_validated: boolean
  holding_sector: string
  portfolio_state: SectorRotationPortfolioState
  sectors: Record<string, SectorRotationStateView>
  decision: SectorRotationDecision
  reason: string
  confidence: number
  llm_validation: SectorRotationLLMValidation | null
  notes: string[]
}

export interface SectorRotationResponse {
  status: SectorRotationStatus
  age_trading_days?: number | null
  stale_threshold_days?: number
  sentiment_source?: string | null
  report_usable?: boolean
  strategy_validated?: boolean
  data: SectorRotationPayload | null
  message?: string
}
