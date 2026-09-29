/** 展示模式：普惠理财通（默认） / 机构量化研报 */
export type ViewMode = 'retail' | 'expert'

/** 语义色，与 tailwind.config.js 中的令牌一一对应 */
export type Tone = 'green' | 'red' | 'blue' | 'gold' | 'orange'

export type MetricIcon = 'shield' | 'rise'

export interface BrandConfig {
  /** 品牌主名，例如 Rainbow-FinGPT */
  name: string
  /** 产品名，例如 银发安心理财助手 */
  product: string
  /** 一句话定位 */
  tagline: string
  /** Logo 资源地址（建议 SVG） */
  logo: string
}

export interface ModeOption {
  id: ViewMode
  label: string
  /** 小屏短标签，例如 普惠 / 研报 */
  short?: string
  /** 选中态下的副标注，例如（默认） */
  note?: string
  icon: 'shield' | 'flask'
}

export interface HeaderData {
  brand: BrandConfig
  modes: ModeOption[]
  user: { label: string }
}

/** Hero 三张核心指标卡 */
export interface HeroMetric {
  id: string
  icon: MetricIcon
  label: string
  value: string
  tone: Tone
  caption: string
  tip?: string
}

/** 资产健康晴雨表（半圆仪表） */
export interface HealthGaugeData {
  title: string
  /** 仪表下方的主结论，例如 当前市场微澜 */
  level: string
  /** 补充说明 */
  desc: string
  /** 防御充分度 0–1，决定绿色弧线长度 */
  percent: number
  tip?: string
}

export interface HeroData {
  title: string
  subtitle: string
  backgroundImage: string
  /** 机构模式下在副标题右侧显示的提示 */
  modeBadge?: string
  metrics: HeroMetric[]
  gauge: HealthGaugeData
}

/* ------------------------------------------------------------------ 03 收益曲线 */

export interface CurveSeries {
  name: string
  /** 直接展示的收益率文案，例如 +8.76% */
  returnLabel: string
  /** 与 dates 等长的百分比数值（不带 % 号） */
  series: number[]
}

export interface EquityCurveData {
  dates: string[]
  portfolio: CurveSeries
  benchmark: CurveSeries & { note: string }
}

/* ------------------------------------------------------------------ 04 资产配置 */

export interface AllocationSegment {
  key: string
  name: string
  /** 百分比权重，三项合计 100 */
  weight: number
  color: string
}

export interface CashNoteData {
  title: string
  body: string
  /** 展开后的补充说明 */
  details: string[]
}

/* ------------------------------------------------------------------ 05 事件流 */

export interface RiskEvent {
  id: string
  tone: Tone
  icon: 'shield' | 'arrowUp'
  title: string
  /** 相对时间，例如 2天前 */
  timeAgo: string
  content: string
  /** 数据缺失或不可点击时展示禁用态 */
  disabled?: boolean
}

/* ------------------------------------------------------------------ 06 机构量化研报（策略表现） */

/** 相关性矩阵：N×N 对称矩阵，取值 -1 ~ 1 */
export interface CorrelationMatrix {
  labels: string[]
  matrix: number[][]
}

/** 单个策略的表现（来自 quantitative/latest_evolution.json） */
export interface StrategyRow {
  key: string
  name: string
  /** 累计收益率（%） */
  cumulativeReturnPct: number | null
  /** 夏普比率 */
  sharpe: number | null
  /** 最大回撤（%） */
  maxDrawdownPct: number | null
  /** 胜率（%） */
  winRatePct: number | null
  /** 综合评分 */
  score: number | null
  /** 回测交易日数 */
  tradingDays: number | null
  /** 是否为当周冠军策略 */
  isChampion: boolean
  rank: number
  /** 形如 1/15 的排名文案 */
  rankText: string
}

/** 策略净值曲线的一条序列 */
export interface StrategyNavSeries {
  key: string
  label: string
  color: string
  /** 与 nav.dates 等长的累计收益率（%） */
  series: number[]
  returnPct: number | null
}

export interface ExpertData {
  strategies: StrategyRow[]
  /** 参与排名的策略总数 */
  strategyTotal: number
  nav: {
    dates: string[]
    series: StrategyNavSeries[]
  }
  /** 回测数据不可用时为 null */
  correlation: CorrelationMatrix | null
}

/* ------------------------------------------------------------------ 07 学术因子与计量定价 */

/** Fama-MacBeth 回归因子行 */
export interface FamaMacBethFactor {
  name: string
  beta: number
  tStat: number
  pValue: string
  interpretation: string
}

/** CSMAR 字段映射行 */
export interface CsmarFieldMapping {
  variable: string
  openSource: string
  windField: string
  csmarField: string
}

/** Soft-Spearman Rank IC 行 */
export interface RankIcRow {
  horizon: string
  staticIc: number
  temporalIc: number
  icIr: number
  harveyLiuT: number
  improvement: string
  isHighlight?: boolean
}

/** NALE 拓扑矩阵 */
export interface NaleTopologyMatrix {
  labels: string[]
  matrix: number[][]
}

/** BibTeX 引用 */
export interface AcademicCitation {
  bibtex: string
  paperUrl?: string
  paperTitle: string
}

/** 学术计量数据聚合 */
export interface AcademicEconometricsData {
  famaMacBeth: FamaMacBethFactor[]
  csmarMapping: CsmarFieldMapping[]
  rankIc: RankIcRow[]
  naleTopology: NaleTopologyMatrix
  citation: AcademicCitation
  notes: {
    spilloverCapture: string
    factorHalfLife: string
    placeboTest: string
    trendGate: string
  }
}

/* ------------------------------------------------------------------ 后端视图模型 */

/**
 * GET /api/v1/homepage 的响应。
 * 字段与各区块组件的 props 一一对应，取到后可直接下传，无需在组件里做映射。
 */
export interface HomepageResponse {
  generated_at: string
  hero: Pick<HeroData, 'title' | 'subtitle' | 'metrics' | 'gauge'>
  equityCurve: EquityCurveData
  allocation: AllocationSegment[]
  cashNote: CashNoteData
  riskEvents: RiskEvent[]
  expert: ExpertData
  academic?: AcademicEconometricsData
  meta?: {
    points?: number
    sources?: Record<string, string>
  }
}
