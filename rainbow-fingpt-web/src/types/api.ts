/**
 * 后端接口类型 —— 由 openapi.json 自动生成，请勿手工修改。
 *
 * 来源 spec：Rainbow-FinGPT API v1 v1.0.0（OpenAPI 3.0.3）
 * schema 数：39
 *
 * 重新生成：npm run api:spec && npm run api:types
 */

/* ------------------------------------------------------------------ Schemas */

/**
 * 统一错误响应体，沿用本项目的既有风格。
 */
export interface ApiError {
  /**
   * 错误描述，可直接展示给用户或用于日志检索。
   * @example "参数 page_size 超出取值范围"
   */
  error: string
  /**
   * 可选的补充说明，包含具体取值 / 允许范围等排障信息。
   * @example "应在 [1, 200] 之间，收到 500"
   */
  detail?: string
}

/**
 * 各维度评分。总分 `total` 是前端列表默认的排序依据；缺失维度为 null。
 */
export interface Scores {
  /**
   * 综合总分（v3 引擎为风险调整后总分），列表默认按它排序。
   * @example 45.7
   */
  total: number | null
  /**
   * 风险调整后得分，与总分同源。
   * @example 45.7
   */
  risk_adjusted: number | null
  /**
   * 基本面评分（基本面作为门禁，未覆盖时为 null）。
   * @example 59.5
   */
  fundamental: number | null
  /**
   * 技术面评分，0–100。
   * @example 100.0
   */
  technical: number | null
  /**
   * 行业轮动评分，0–100。
   * @example 57.0
   */
  industry: number | null
  /**
   * 领先指标评分，0–100。
   * @example 20.0
   */
  leading: number | null
}

/**
 * 行情快照，来自 `docs/data/summary.json`；该标的没有行情记录时为 null。
 */
export interface Market {
  /**
   * 最新收盘价（元）。
   * @example 351.0
   */
  last_close: number | null
  /**
   * 最新交易日涨跌幅（%），正数为上涨。
   * @example 0.43
   */
  change_pct: number | null
  /**
   * 最新交易日涨跌额（元）。
   * @example 1.5
   */
  change_amt: number | null
  /**
   * 行情对应交易日（YYYY-MM-DD）。
   * @example "2026-09-04"
   */
  last_date: string | null
  /**
   * 行情抓取状态，`ok` 表示正常。
   * @example "ok"
   */
  status: string | null
}

/**
 * 风险画像。
 */
export interface Risk {
  /**
   * 风险等级；数据缺失时为 `unknown`。
   * @example "low"
   */
  level: "low" | "medium" | "high" | "unknown"
  /**
   * 风险等级的中文标签。
   * @example "低风险"
   */
  label: string
  /**
   * 风险得分，数值越高代表风险越大。
   * @example 19.0
   */
  score: number | null
  /**
   * 20 日年化波动率（%）。
   * @example 20.98
   */
  annualized_volatility_20d_pct: number | null
  /**
   * 60 日最大回撤（%），通常为负值。
   * @example -8.73
   */
  max_drawdown_60d_pct: number | null
  /**
   * ATR(14) 占价格百分比（%），衡量短期波动。
   * @example 1.97
   */
  atr14_pct: number | null
}

/**
 * 短周期收益预测（KNN / 领先指标模型）。
 */
export interface Forecast {
  /**
   * 未来 3 日预测收益率（%）。
   * @example -0.37
   */
  return_3d_pct: number | null
  /**
   * 未来 5 日预测收益率（%）。
   * @example 0.12
   */
  return_5d_pct: number | null
  /**
   * 未来 3 日上涨概率（%）。
   * @example 26.7
   */
  up_probability_3d_pct: number | null
  /**
   * 未来 5 日上涨概率（%）。
   * @example 46.7
   */
  up_probability_5d_pct: number | null
  /**
   * 预测置信度，`low` / `medium` / `high`。
   * @example "medium"
   */
  confidence: string | null
  /**
   * 模型给出的建议持有天数。
   * @example 5.0
   */
  optimal_holding_days: number | null
}

/**
 * 技术面指标。
 */
export interface Technical {
  /**
   * 趋势方向。
   * @example "uptrend"
   */
  trend: "uptrend" | "downtrend" | "range" | "rebound" | "unknown" | null
  /**
   * 14 日相对强弱指标，0–100，大于 70 通常视为超买。
   * @example 74.2
   */
  rsi14: number | null
  /**
   * 5 日量比，大于 1 表示放量。
   * @example 1.92
   */
  volume_ratio_5d: number | null
  /**
   * 近 5 日收益率（%）。
   * @example 2.51
   */
  return_5d_pct: number | null
  /**
   * 近 20 日收益率（%）。
   * @example 1.59
   */
  return_20d_pct: number | null
}

/**
 * 所属行业 / 板块的相对表现。
 */
export interface Industry {
  /**
   * 行业或板块名称。
   * @example "农产品大宗"
   */
  name: string | null
  /**
   * 行业近 5 日收益率（%）。
   * @example -3.02
   */
  return_5d_pct: number | null
  /**
   * 行业近 20 日收益率（%）。
   * @example -3.44
   */
  return_20d_pct: number | null
  /**
   * 相对基准指数的 20 日超额收益（%）。
   * @example 16.17
   */
  relative_strength_20d_pct: number | null
}

/**
 * 板块网络（NALE）位置，用于判断标的在产业链中的角色与共振强度。
 */
export interface Sector {
  /**
   * 板块名称。
   * @example "贵金属弹性"
   */
  name: string | null
  /**
   * 产业链层级角色，如 `core_mid` / `neutral`。
   * @example "core_mid"
   */
  tier_role: string | null
  /**
   * 板块内上涨标的占比（%）。
   * @example 100.0
   */
  breadth_pct: number | null
  /**
   * 板块内是否存在涨停共振。
   * @example false
   */
  has_limit_up_resonance: boolean | null
  /**
   * 同涨同跌的关联标的数量。
   * @example 3
   */
  co_movement_peers: number | null
}

/**
 * 交易信号与操作建议，前端可直接映射成标签或提示语。
 */
export interface Signal {
  /**
   * 赔率类型，如 `range_bound`（震荡）/ `trend_up`（趋势上行）。
   * @example "range_bound"
   */
  bet_type: string | null
  /**
   * 是否通过基本面门禁；未通过通常不建议纳入组合。
   * @example true
   */
  fundamental_gate_passed: boolean | null
  /**
   * 未通过门禁时的原因。
   */
  fundamental_gate_reason: string | null
  /**
   * 建议持有天数。
   * @example 20
   */
  holding_period: number | null
  /**
   * 建议交易频率，`low` / `medium` / `high`。
   * @example "medium"
   */
  trade_frequency: string | null
  /**
   * 一句话操作建议。
   * @example "震荡股：均值回归或观望，避免追涨杀跌"
   */
  recommendation: string | null
  /**
   * 异动强度得分。
   * @example 18.8
   */
  monster_score: number | null
  /**
   * 年化波动率（小数形式，0.4344 即 43.44%）。
   * @example 0.4344
   */
  volatility_annual: number | null
}

/**
 * 基本面明细，仅当 `include_fundamental=true` 时返回；无数据时为 null。
 */
export interface Fundamental {
  /**
   * 基本面总分。
   * @example 59.5
   */
  score: number | null
  /**
   * 财报报告期（YYYY-MM-DD）。
   * @example "2026-03-31"
   */
  report_date: string | null
  /**
   * 四个基本面维度的得分（0–100）。
   */
  dimensions: {
    /**
     * 资产质量得分。
     * @example 50.0
     */
    asset_quality: number | null
    /**
     * 负债安全性得分。
     * @example 63.0
     */
    liability_safety: number | null
    /**
     * 盈利质量得分。
     * @example 73.0
     */
    profit_quality: number | null
    /**
     * 现金流健康度得分。
     * @example 52.6
     */
    cash_health: number | null
  }
  /**
   * 正面解读。
   * @example "净利润同比 +1.4%"
   */
  positive_view: string | null
  /**
   * 反面解读 / 风险提示。
   * @example "经营现金流/净利润 0.99，利润兑现存疑"
   */
  negative_view: string | null
}

/**
 * 评分归因明细，解释分数是怎么来的。
 */
export interface Reason {
  /**
   * 归因方向。当前数据集出现 positive / negative / warning，可能为 null；流水线新增取值时同样返回。
   * @example "positive"
   */
  type: string | null
  /**
   * 归因标题。
   * @example "中短期趋势向上"
   */
  title: string
  /**
   * 归因说明。
   * @example "收盘价位于20日和60日均线上方。"
   */
  detail: string
  /**
   * 对总分的贡献值，负数为扣分。
   * @example 8.0
   */
  contribution: number | null
}

/**
 * 数据集中的一行（一只标的）。由排行榜主表、行情快照与基本面按 code 关联后扁平化得到；所有缺失值统一为 null，浮点数已定点到两位小数。
 */
export interface DatasetRow {
  /**
   * 榜单排名，从 1 开始。
   * @example 1
   */
  rank: number
  /**
   * 标的代码，如 600519 / 510300 / MU。
   * @example "159562"
   */
  code: string
  /**
   * 标的名称。
   * @example "黄金股ETF"
   */
  name: string
  /**
   * 标的类型。
   * @example "etf"
   */
  type: "stock" | "etf"
  /**
   * 分类 / 行业标签。
   * @example "贵金属弹性"
   */
  category: string
  /**
   * 评分对应的交易日（YYYY-MM-DD）。
   * @example "2026-09-04"
   */
  trade_date: string
  /**
   * 该行数据是否已过期（当日流水线未更新则为 true）。
   * @example false
   */
  stale: boolean
  scores: Scores
  market: Market | null
  risk: Risk
  forecast: Forecast
  technical: Technical
  industry: Industry
  sector: Sector
  signal: Signal
  fundamental: Fundamental | null
  /**
   * 评分归因列表。
   */
  reasons: Reason[]
}

/**
 * 筛选维度的一个取值及其命中数量。
 */
export interface FacetValue {
  /**
   * 取值。
   * @example "存储"
   */
  value: string
  /**
   * 命中的标的数量。
   * @example 9
   */
  count: number
}

/**
 * 筛选器取值分布，基于过滤后的全量结果（不受分页影响），按数量降序。
 */
export interface Facets {
  /**
   * 标的类型分布。
   */
  type: FacetValue[]
  /**
   * 分类分布。
   */
  category: FacetValue[]
  /**
   * 风险等级分布。
   */
  risk_level: FacetValue[]
  /**
   * 趋势分布。
   */
  trend: FacetValue[]
}

/**
 * 过滤条件，字段与 `GET /api/v1/dataset` 的查询参数一一对应。
 */
export interface DatasetFilter {
  /**
   * 关键词，匹配代码、名称或分类。
   * @example "存储"
   */
  q?: string
  /**
   * 标的代码白名单。
   * @example ["600519", "300750"]
   */
  codes?: string[]
  /**
   * 标的类型白名单。
   * @example ["stock"]
   */
  type?: ("stock" | "etf")[]
  /**
   * 分类白名单（精确匹配）。
   * @example ["存储", "科技"]
   */
  category?: string[]
  /**
   * 风险等级白名单。
   * @example ["low"]
   */
  risk_level?: ("low" | "medium" | "high")[]
  /**
   * 趋势白名单。
   * @example ["uptrend"]
   */
  trend?: ("uptrend" | "downtrend" | "range" | "rebound")[]
  /**
   * 只保留已过期 / 未过期的数据。
   * @example false
   */
  stale?: boolean
  /**
   * 总分下限。
   * @example 30
   */
  min_score?: number
  /**
   * 总分上限。
   * @example 60
   */
  max_score?: number
}

/**
 * 分页与数据源元信息。
 */
export interface DatasetMeta {
  /**
   * 主表相对路径。
   * @example "analysis/ranking_v3.json"
   */
  source: string
  /**
   * 数据集对应的交易日。
   * @example "2026-09-04"
   */
  trade_date: string
  /**
   * 流水线生成该数据集的时间。
   * @example "2026-09-06 00:17:35+08:00"
   */
  generated_at: string
  /**
   * 生成该数据集的引擎版本。
   * @example "v3.0-leading-first"
   */
  engine?: string
  /**
   * 总分计算公式说明。
   * @example "Opportunity = 0.45*Leading + 0.30*KNN + 0.25*Tech, Fundamental=Gatekeeper"
   */
  formula?: string
  /**
   * 实际生效的排序，格式为 `字段:方向`。
   * @example "rank:asc"
   */
  sort: string
  /**
   * 回显本次生效的过滤条件，便于前端对齐状态。
   */
  filters: Record<string, unknown>
  /**
   * 过滤后的命中总条数（不受分页影响）。
   * @example 156
   */
  total: number
  /**
   * 当前页码（超出总页数时已被收敛到最后一页）。
   * @example 1
   */
  page: number
  /**
   * 每页条数。
   * @example 20
   */
  page_size: number
  /**
   * 总页数。
   * @example 8
   */
  total_pages: number
  /**
   * 是否存在下一页。
   * @example true
   */
  has_next: boolean
  /**
   * 是否存在上一页。
   * @example false
   */
  has_prev: boolean
  /**
   * 本页实际返回的条数。
   * @example 20
   */
  returned: number
  facets?: Facets
}

/**
 * 分页数据集响应。
 */
export interface DatasetResponse {
  meta: DatasetMeta
  /**
   * 当前页的数据行。
   */
  items: DatasetRow[]
}

/**
 * 一组数值的分布摘要；无有效数值时为 null。
 */
export interface Describe {
  /**
   * 平均值。
   * @example 27.34
   */
  avg: number
  /**
   * 中位数。
   * @example 25.9
   */
  median: number
  /**
   * 最小值。
   * @example 3.2
   */
  min: number
  /**
   * 最大值。
   * @example 45.7
   */
  max: number
}

/**
 * 分类维度的统计结果。
 */
export interface CategoryStat {
  /**
   * 分类名称。
   * @example "存储"
   */
  category: string
  /**
   * 该分类下命中的标的数量。
   * @example 9
   */
  count: number
  /**
   * 该分类下的平均总分。
   * @example 23.4
   */
  avg_score: number | null
}

/**
 * 对选中标的的聚合统计，用于面板顶部的总览卡片。
 */
export interface Stats {
  /**
   * 参与统计的标的数量。
   * @example 10
   */
  count: number
  score?: Describe | null
  risk_score?: Describe | null
  volatility_20d_pct?: Describe | null
  max_drawdown_60d_pct?: Describe | null
  /**
   * 预测维度的统计摘要。
   */
  forecast?: {
    return_5d_pct?: Describe | null
    up_probability_5d_pct?: Describe | null
  }
  /**
   * 风险等级分布。
   */
  risk_level_distribution: FacetValue[]
  /**
   * 标的类型分布。
   */
  type_distribution: FacetValue[]
  /**
   * 趋势分布。
   */
  trend_distribution: FacetValue[]
  /**
   * 分类统计，按数量降序取前 10。
   */
  category_top: CategoryStat[]
  /**
   * 其中数据已过期的标的数量。
   * @example 0
   */
  stale_count: number
}

/**
 * 组合中的一个持仓建议。
 */
export interface Position {
  /**
   * 标的代码。
   * @example "159562"
   */
  code: string
  /**
   * 标的名称。
   * @example "黄金股ETF"
   */
  name: string
  /**
   * 分类 / 行业。
   * @example "贵金属弹性"
   */
  category: string
  /**
   * 目标权重（0–1 的小数）。
   * @example 0.125
   */
  weight: number
  /**
   * 目标权重（百分比形式，便于直接展示）。
   * @example 12.5
   */
  amount_pct: number
  /**
   * 该标的的总分。
   * @example 45.7
   */
  score: number | null
  /**
   * 风险等级。
   * @example "low"
   */
  risk_level: string
  /**
   * 20 日年化波动率（%）。
   * @example 20.98
   */
  volatility_20d_pct: number | null
}

/**
 * 组合权重分配结果（仅 `operation=allocate` 返回）。
 */
export interface Allocation {
  /**
   * 权重方法。
   * @example "score"
   */
  method: "equal" | "score" | "risk_inverse"
  /**
   * 单标的上限。
   * @example 0.25
   */
  max_weight: number
  /**
   * 已分配的总权重，正常情况下为 1。
   * @example 1.0
   */
  invested_weight: number
  /**
   * 剩余现金权重；因上限约束无法满仓时大于 0。
   * @example 0.0
   */
  cash_weight: number
  /**
   * 持仓建议，按权重降序。
   */
  positions: Position[]
  /**
   * 分配过程中的提示，例如上限约束不可行时的说明。
   * @example ["标的数量不足，无法在 max_weight=0.05 下用满仓位，剩余记为现金"]
   */
  notes: string[]
}

/**
 * 处理请求。`operation=screen` 只做筛选排序；`allocate` 额外给出组合权重；`stats` 只看聚合统计。三者共用同一套数据集逻辑，结果口径完全一致。
 */
export interface ProcessRequest {
  /**
   * 处理类型，默认 `screen`。
   * @example "allocate"
   */
  operation?: "screen" | "allocate" | "stats"
  filters?: DatasetFilter
  /**
   * 取前 N 只标的，1–200，默认 20。
   * @example 10
   */
  top_n?: number
  /**
   * 权重方法，仅 `allocate` 有效：`equal` 等权、`score` 按总分比例、`risk_inverse` 按波动率倒数（风险平价）。
   * @example "risk_inverse"
   */
  weighting?: "equal" | "score" | "risk_inverse"
  /**
   * 单标的上限（0–1]，默认 0.25；超出部分按比例回填给未触顶的标的。
   * @example 0.25
   */
  max_weight?: number
  /**
   * 排序字段，写法同 GET 接口的 `sort`。
   * @example "-total_score"
   */
  sort?: string
  /**
   * 字段裁剪，只返回指定顶层字段。
   * @example ["code", "name", "scores", "risk"]
   */
  fields?: string[]
  /**
   * 是否附带基本面明细。
   * @example false
   */
  include_fundamental?: boolean
  /**
   * 是否在 meta 中返回筛选器取值分布。
   * @example false
   */
  with_facets?: boolean
}

/**
 * 处理结果。
 */
export interface ProcessResponse {
  /**
   * 本次实际执行的 operation（已回显）。
   * @example "allocate"
   */
  operation: string
  /**
   * 服务端处理时间（ISO 8601，带时区）。
   * @example "2026-09-27T12:00:00+08:00"
   */
  generated_at: string
  /**
   * 过滤后命中的总条数。
   * @example 42
   */
  matched: number
  /**
   * 本次实际送入处理的条数（≤ top_n）。
   * @example 10
   */
  selected_count: number
  meta: DatasetMeta
  stats: Stats
  allocation?: Allocation
  /**
   * 选中的标的行，结构与 GET 接口一致。
   */
  items: DatasetRow[]
}

/**
 * Hero 区的一项核心指标。数值已由后端格式化，前端直接渲染。
 */
export interface HeroMetric {
  /**
   * 指标标识，用于 React key 与埋点。
   * @example "safety"
   */
  id: string
  /**
   * 图标类型。
   * @example "shield"
   */
  icon: "shield" | "rise"
  /**
   * 指标名称。
   * @example "资产安全评级"
   */
  label: string
  /**
   * 指标展示值（字符串，含符号与单位）。
   * @example "AAA"
   */
  value: string
  /**
   * 语义色，对应前端五色系统。
   * @example "green"
   */
  tone: "green" | "red" | "blue" | "gold" | "orange"
  /**
   * 指标补充说明。
   * @example "极高防御"
   */
  caption: string
  /**
   * 悬浮提示：该指标的计算口径。
   * @example "按组合年化波动率与历史最大回撤映射：回撤 ≤5% 且波动 ≤15% 为 AAA"
   */
  tip?: string
}

/**
 * 资产健康晴雨表：由市场温度模型推导的建议仓位。
 */
export interface HealthGauge {
  /**
   * 卡片标题。
   * @example "资产健康晴雨表"
   */
  title: string
  /**
   * 仪表主结论。
   * @example "市场温度 70.2"
   */
  level: string
  /**
   * 补充说明。
   * @example "正常 ｜ 建议仓位 75.3%"
   */
  desc: string
  /**
   * 防御充分度 0–1，决定仪表绿色弧线长度。
   * @example 0.753
   */
  percent: number
  /**
   * 悬浮提示。
   * @example "由市场温度模型给出的建议仓位比例，越高代表防御系统越有加仓空间"
   */
  tip?: string
}

/**
 * 02 Hero 区块。
 */
export interface HeroBlock {
  /**
   * 主标题。
   * @example "您好！让财富为您的晚年生活保驾护航"
   */
  title: string
  /**
   * 副标题。
   * @example "专业的养老金融解决方案，稳健增值，安心相伴"
   */
  subtitle: string
  /**
   * 三项核心指标。
   */
  metrics: HeroMetric[]
  gauge: HealthGauge
}

/**
 * 一条收益曲线。
 */
export interface CurveSeries {
  /**
   * 曲线名称（组合名 / 基准名）。
   * @example "稳健组合-防守型"
   */
  name: string
  /**
   * 区间收益的展示文案。
   * @example "+12.63%"
   */
  returnLabel: string
  /**
   * 区间累计收益率（%）。
   * @example 12.63
   */
  returnPct?: number | null
  /**
   * 与 equityCurve.dates 等长的累计收益率（%）。
   */
  series: number[]
}

/**
 * 基准收益曲线。相比 CurveSeries 多一个必填的 note 标注。
 */
export interface BenchmarkSeries {
  /**
   * 基准名称。
   * @example "全池等权基准"
   */
  name: string
  /**
   * 基准的补充标注。
   * @example "同期"
   */
  note: string
  /**
   * 区间收益的展示文案。
   * @example "-6.20%"
   */
  returnLabel: string
  /**
   * 区间累计收益率（%）。
   * @example -6.2
   */
  returnPct?: number | null
  /**
   * 与 equityCurve.dates 等长的累计收益率（%）。
   */
  series: number[]
}

/**
 * 组合风险指标，用于填充 Hero 的三项指标。
 */
export interface CurveStats {
  /**
   * 区间最大回撤（%，非正数）。
   * @example -4.22
   */
  maxDrawdownPct: number | null
  /**
   * 年化波动率（%），按 252 个交易日。
   * @example 14.38
   */
  volatilityPct: number | null
  /**
   * 相对同期基准的超额收益（%）。
   * @example 18.83
   */
  excessPct: number | null
  /**
   * 返回的采样点数。
   * @example 21
   */
  samples: number
  /**
   * 累计收益口径。
   * @example "running_sum_of_daily_returns"
   */
  convention: string
}

/**
 * 03 绝对收益曲线区块。累计收益沿用项目既有口径：对日收益率做累加。
 */
export interface EquityCurveBlock {
  /**
   * X 轴日期标签（MM-DD）。
   */
  dates: string[]
  portfolio: CurveSeries
  benchmark: BenchmarkSeries
  stats?: CurveStats
}

/**
 * 资产配置环图的一段（一只持仓或现金）。
 */
export interface AllocationSegment {
  /**
   * 分段标识，持仓为标的代码，现金为 `cash`。
   * @example "300750"
   */
  key: string
  /**
   * 分段名称。
   * @example "宁德时代"
   */
  name: string
  /**
   * 权重（%），所有分段合计精确等于 100。
   * @example 18.1
   */
  weight: number
  /**
   * 分段颜色（十六进制）。
   * @example "#F08634"
   */
  color: string
  /**
   * 入选理由（来自分片数据）。
   * @example "综合分54.3 | 风险33 | 波动平价11.4%"
   */
  reason?: string | null
}

/**
 * 现金策略说明面板。
 */
export interface CashNote {
  /**
   * 面板标题。
   * @example "为什么留 36% 现金？"
   */
  title: string
  /**
   * 正文。
   * @example "当前现金 360,000 元，占总资产 36.0%。因为要确保您随时有应急资金，且在市场风险期不上杠杆。"
   */
  body: string
  /**
   * 展开后的补充说明。
   */
  details: string[]
}

/**
 * 05 产业链避险的一张事件卡。
 */
export interface RiskEvent {
  /**
   * 事件标识。
   * @example "sentiment-watch"
   */
  id: string
  /**
   * 语义色。
   * @example "green"
   */
  tone: "green" | "red" | "blue" | "gold" | "orange"
  /**
   * 图标类型。
   * @example "shield"
   */
  icon: "shield" | "arrowUp"
  /**
   * 事件标题。
   * @example "情绪面监测"
   */
  title: string
  /**
   * 相对时间文案。
   * @example "1个月前"
   */
  timeAgo: string
  /**
   * 事件正文。
   * @example "已跟踪 144 个事件样本：正向超预期 26 次、负向意外 10 次，整体情绪偏中性。"
   */
  content: string
}

/**
 * 单个策略的表现（来自 quantitative/latest_evolution.json）。
 */
export interface StrategyRow {
  /**
   * 策略标识。
   * @example "aggressive_v2"
   */
  key: string
  /**
   * 策略显示名。
   * @example "动态止盈止损优化版"
   */
  name: string
  /**
   * 累计收益率（%）。
   * @example 6.52
   */
  cumulativeReturnPct: number | null
  /**
   * 夏普比率。
   * @example 0.55
   */
  sharpe: number | null
  /**
   * 最大回撤（%）。
   * @example 1.25
   */
  maxDrawdownPct: number | null
  /**
   * 胜率（%）。
   * @example 57.1
   */
  winRatePct: number | null
  /**
   * 综合评分，策略排名的依据。
   * @example 10.61
   */
  score: number | null
  /**
   * 回测交易日数。
   * @example 7
   */
  tradingDays: number | null
  /**
   * 是否为当周冠军策略。
   * @example true
   */
  isChampion: boolean
  /**
   * 排名（从 1 开始）。
   * @example 1
   */
  rank: number
  /**
   * 排名的展示文案。
   * @example "1/15"
   */
  rankText: string
}

/**
 * 策略净值曲线的一条序列。
 */
export interface StrategyNavSeries {
  /**
   * 序列标识。
   * @example "nav_dynamic_alpha_tnale"
   */
  key: string
  /**
   * 序列显示名。
   * @example "动态 Alpha"
   */
  label: string
  /**
   * 线色（十六进制）。
   * @example "#E9A93B"
   */
  color: string
  /**
   * 与 expert.nav.dates 等长的累计收益率（%）。
   */
  series: number[]
  /**
   * 区间累计收益率（%）。
   * @example 169.16
   */
  returnPct: number | null
}

/**
 * 相关性矩阵：由策略日收益现算，N×N 对称，主对角线为 1。
 */
export interface CorrelationMatrix {
  /**
   * 行列标签。
   */
  labels: string[]
  /**
   * 相关系数矩阵，取值 -1 ~ 1。
   */
  matrix: number[][]
}

/**
 * 06 机构量化研报模式（策略表现）区块。
 */
export interface ExpertBlock {
  /**
   * 策略对比表（按综合评分降序，取前 4）。
   */
  strategies: StrategyRow[]
  /**
   * 参与排名的策略总数。
   * @example 15
   */
  strategyTotal: number
  /**
   * 策略净值走势。
   */
  nav: {
    /**
     * X 轴日期标签（MM-DD）。
     */
    dates: string[]
    /**
     * 策略与基准的净值序列。
     */
    series: StrategyNavSeries[]
  }
  correlation: CorrelationMatrix | null
}

/**
 * 首页视图模型：一次请求返回 02–06 五个区块的全部动态数据。 字段与前端各组件的 props 一一对应，前端取到后可直接下传，不必在浏览器里再做聚合。任一数据源缺失时对应区块退化为空/兜底值，而不是整页 500。
 */
export interface HomepageResponse {
  /**
   * 服务端组装时间（ISO 8601，带时区）。
   * @example "2026-09-27T14:05:00+08:00"
   */
  generated_at: string
  hero: HeroBlock
  equityCurve: EquityCurveBlock
  /**
   * 资产配置分段（持仓 + 现金），权重合计 100。
   */
  allocation: AllocationSegment[]
  cashNote: CashNote
  /**
   * 产业链避险事件卡（最多 3 张）。
   */
  riskEvents: RiskEvent[]
  expert: ExpertBlock
  /**
   * 采样参数与数据来源，便于排查数字出处。
   */
  meta?: {
    /**
     * 收益曲线采样点数。
     * @example 21
     */
    points?: number
    /**
     * 各区块的数据来源文件（区块名 → 文件路径）。
     */
    sources?: Record<string, string>
  }
}

/* ------------------------------------------------------------------ 接口 DTO */

/** GET /api/v1/dataset —— 分页查询数据集 */
export interface ListDatasetQuery {
  /**
   * 关键词模糊匹配：同时匹配股票代码、名称与分类（不区分大小写）。例如 `600519`、`茅台`、`存储`。
   * @example "存储"
   */
  q?: string
  /**
   * 按标的代码精确过滤。多个代码用英文逗号分隔，如 `codes=600519,300750`。
   * @example ["600519", "300750"]
   */
  codes?: string[]
  /**
   * 按标的类型过滤。多个类型用英文逗号分隔，如 `type=stock,etf`。
   * @example ["stock"]
   */
  type?: ("stock" | "etf")[]
  /**
   * 按分类 / 行业过滤（精确匹配）。多个分类用英文逗号分隔；取值可先用 `with_facets=1` 拉取。
   * @example ["存储"]
   */
  category?: string[]
  /**
   * 按风险等级过滤。多个等级用英文逗号分隔，如 `risk_level=low,medium`。
   * @example ["low", "medium"]
   */
  risk_level?: ("low" | "medium" | "high")[]
  /**
   * 按技术面趋势过滤。多个取值用英文逗号分隔。取值来自数据集自身的技术面判断：`uptrend` 上行、`downtrend` 下行、`range` 区间震荡、`rebound` 反弹；流水线新增取值时本参数同样接受。可用 `with_facets=1` 获取当前真实分布。
   * @example ["uptrend"]
   */
  trend?: ("uptrend" | "downtrend" | "range" | "rebound")[]
  /**
   * 是否只看数据过期（`true`）或未过期（`false`）的标的；不传则不过滤。
   * @example false
   */
  stale?: boolean
  /**
   * 总分（`scores.total`）下限，闭区间。
   * @example 30
   */
  min_score?: number
  /**
   * 总分（`scores.total`）上限，闭区间。
   * @example 60
   */
  max_score?: number
  /**
   * 排序字段，默认 `rank` 升序。降序支持 `-total_score` 或 `total_score:desc` 两种写法。可排序字段：rank, code, name, trade_date, total_score, risk_adjusted_score, fundamental_score, technical_score, industry_score, leading_score, last_close, change_pct, volatility_20d_pct, max_drawdown_60d_pct, return_5d_pct, up_probability_5d_pct, rsi14。空值一律排在最后。
   * @example "-total_score"
   */
  sort?: string
  /**
   * 页码，从 1 开始；超出总页数时自动返回最后一页。
   * @example 1
   */
  page?: number
  /**
   * 每页条数，1–200，默认 20。
   * @example 20
   */
  page_size?: number
  /**
   * 字段裁剪：只返回指定顶层字段，逗号分隔，用于减小响应体积。可选：rank, code, name, type, category, trade_date, stale, scores, market, risk, forecast, technical, industry, sector, signal, fundamental, reasons。 ⚠️ 使用本参数后，`items` 是**稀疏对象**：只有被选中的字段存在，不再满足 `DatasetRow` 的全部必填约束。前端应把返回项按 `Partial<DatasetRow>` 处理（本项目 `fetchDataset` 已为重载，传 `fields` 时自动返回 `Partial<DatasetRow>[]`），不要直接访问未选中的字段。
   * @example ["code", "name", "scores"]
   */
  fields?: string[]
  /**
   * 是否附带基本面明细（逐行读取 `docs/data/fundamental/<code>.json`，只读当前页）。默认关闭。
   * @example true
   */
  include_fundamental?: boolean
  /**
   * 是否在 `meta.facets` 中返回各筛选维度的取值分布（基于过滤后的全量结果，不受分页影响），便于前端渲染筛选器。
   * @example true
   */
  with_facets?: boolean
}
export type ListDatasetResponse = DatasetResponse

/** POST /api/v1/process —— 处理前端请求（选股 / 组合权重 / 统计） */
export type ProcessDatasetRequest = ProcessRequest
export type ProcessDatasetResponse = ProcessResponse

/** GET /api/v1/homepage —— 获取首页视图模型 */
export interface GetHomepageQuery {
  /**
   * 收益曲线的采样点数，8–120，默认 21（与设计稿的 7 个 X 轴刻度对齐）。
   * @example 21
   */
  points?: number
}
export type GetHomepageResponse = HomepageResponse

/** GET /api/v1/openapi.json —— 获取本接口的 OpenAPI 规格 */
export type GetOpenApiSpecResponse = Record<string, unknown>
