import type {
  AcademicEconometricsData,
  AllocationSegment,
  CashNoteData,
  EquityCurveData,
  ExpertData,
  HeaderData,
  HeroData,
  RiskEvent,
  ViewMode,
} from '@/types'
// 图片走 Vite 资源管线（而不是 public/ 静态目录）：
// 普通构建会输出成带哈希的 /home/assets/*.jpg，离线构建时可被内联成 data URI 打成单文件。
import heroBackground from '@/assets/hero-bg-v2.jpg'
import logoImage from '@/assets/logo.png'

/**
 * 演示数据。文案与数值全部来自设计稿实测，
 * 接口不可用时由 useHomepage 回退到这里，保证页面离线也能完整渲染。
 */

export const headerData: HeaderData = {
  brand: {
    name: 'Rainbow-FinGPT',
    product: '银发安心理财助手',
    tagline: '面向养老金融的微观因素风险底座',
    logo: logoImage,
  },
  modes: [
    { id: 'retail', label: '普惠理财通模式', short: '普惠', note: '（默认）', icon: 'shield' },
    { id: 'expert', label: '机构量化研报模式', short: '研报', icon: 'flask' },
  ],
  user: { label: '我的' },
}

export const heroData: HeroData = {
  title: '您好！让财富为您的晚年生活保驾护航',
  subtitle: '专业的养老金融解决方案，稳健增值，安心相伴',
  backgroundImage: heroBackground,
  metrics: [
    {
      id: 'safety',
      icon: 'shield',
      label: '资产安全评级',
      value: 'AAA',
      tone: 'green',
      caption: '极高防御',
      tip: '按组合年化波动率与历史最大回撤映射：回撤 ≤5% 且波动 ≤15% 为 AAA',
    },
    {
      id: 'drawdown-resist',
      icon: 'rise',
      label: '震荡市抗跌实绩',
      value: '+18.83%',
      tone: 'red',
      caption: '组合相对同期基准的超额收益',
      tip: '统计区间内组合累计收益与同期基准收益之差',
    },
    {
      id: 'max-drawdown',
      icon: 'shield',
      label: '历史最大回撤控制',
      value: '4.22%',
      tone: 'blue',
      caption: '净值自区间高点的最大跌幅',
      tip: '由组合累计净值序列逐日滚动计算',
    },
  ],
  gauge: {
    title: '资产健康晴雨表',
    level: '市场温度 70.2',
    desc: '正常 ｜ 建议仓位 75.3%',
    percent: 0.753,
    tip: '由市场温度模型给出的建议仓位比例，越高代表防御系统越有加仓空间',
  },
}

/** 机构模式下的 Hero：同一套内容，只追加模式提示，避免凭空编造数据 */
export function heroForMode(mode: ViewMode): HeroData {
  return mode === 'expert' ? { ...heroData, modeBadge: '机构量化研报模式' } : heroData
}

/* ------------------------------------------------------------------ 03 绝对收益曲线 */

/**
 * 21 个采样点，与 EquityCurveChart 的 X_LABEL_INDEX = [0,3,6,9,12,16,20] 对齐。
 * 数值为接口返回的真实快照（累加口径），接口不可用时用它可以完整渲染。
 */
export const equityCurveData: EquityCurveData = {
  dates: ['06-01', '06-04', '06-10', '06-15', '06-19', '06-24', '06-30', '07-03', '07-09', '07-14',
          '07-17', '07-23', '07-28', '08-03', '08-06', '08-12', '08-17', '08-21', '08-26', '09-01', '09-04'],
  portfolio: {
    name: '稳健组合-防守型',
    returnLabel: '+12.63%',
    series: [0, 5.37, 7.42, 7.1, 5.23, 5.09, 4.76, 5.24, 5.39, 6.32,
             5.92, 3.38, 4.85, 3.72, 5.95, 4.41, 7.62, 8.76, 10.09, 13.56, 12.63],
  },
  benchmark: {
    name: '全池等权基准',
    note: '同期',
    returnLabel: '-6.20%',
    series: [0, 1.8, 3.4, 3.26, 0.48, -0.55, -1.48, -3.13, -3.83, -2.64,
             -2.83, -6.16, -4.74, -6.67, -5.77, -7.71, -5.46, -4.83, -5.05, -5.38, -6.2],
  },
}

/* ------------------------------------------------------------------ 04 资产配置 */

export const allocationData: AllocationSegment[] = [
  { key: '159981', name: '能源化工ETF', weight: 11.4, color: '#26A17F' },
  { key: '003095', name: '中欧医疗健康混合A', weight: 13.2, color: '#3D87E8' },
  { key: '300750', name: '宁德时代', weight: 18.1, color: '#F08634' },
  { key: '688036', name: '传音控股', weight: 10.9, color: '#E9A93B' },
  { key: '603019', name: '中科曙光', weight: 10.3, color: '#F0515A' },
  { key: 'cash', name: '高流动性现金管理', weight: 36.1, color: '#F08634' },
]

export const cashNoteData: CashNoteData = {
  title: '为什么留 36% 现金？',
  body: '当前现金 360,000 元，占总资产 36.0%。因为要确保您随时有应急资金，且在市场风险期不上杠杆。',
  details: [
    '应急储备：突发医疗或家庭支出时无需被动赎回。',
    '波动缓冲：市场急跌时现金仓位可平滑净值曲线。',
    '再平衡弹药：极端低估时才有加仓的能力。',
  ],
}

/* ------------------------------------------------------------------ 05 产业链避险 */

export const riskEvents: RiskEvent[] = [
  {
    id: 'sentiment-watch',
    tone: 'green',
    icon: 'shield',
    title: '情绪面监测',
    timeAgo: '1个月前',
    content: '已跟踪 144 个事件样本：正向超预期 26 次、负向意外 10 次，整体情绪偏中性，未出现系统性恶化信号。',
  },
  {
    id: 'event-alpha',
    tone: 'blue',
    icon: 'arrowUp',
    title: '事件驱动超额',
    timeAgo: '1个月前',
    content: '事件发布后 5 日平均超额收益 +0.79%，模型对齐率 35.0%。',
  },
  {
    id: 'position-adjust',
    tone: 'orange',
    icon: 'shield',
    title: '智能仓位调节',
    timeAgo: '1个月前',
    content: '当前市场温度 70.2，建议仓位 75.3%，风险期自动降低敞口、落袋为安。',
  },
]

/* ------------------------------------------------------------------ 06 机构量化研报（策略表现） */

/** 策略净值曲线的 23 个采样点，与 StrategyNavChart 的刻度下标对齐 */
const strategyNavDates = ['03-26', '05-06', '06-14', '07-24', '09-03', '10-14', '11-22', '01-01',
                          '02-11', '03-24', '05-02', '06-11', '07-22', '09-01', '10-10', '11-20',
                          '12-30', '02-09', '03-20', '04-30', '06-09', '07-20', '08-28']

export const expertData: ExpertData = {
  strategies: [
    { key: 'aggressive_v2', name: '动态止盈止损优化版', cumulativeReturnPct: 6.52, sharpe: 0.55, maxDrawdownPct: 1.25, winRatePct: 57.1, score: 10.61, tradingDays: 7, isChampion: true, rank: 1, rankText: '1/15' },
    { key: 'robust', name: '组合_robust', cumulativeReturnPct: 2.81, sharpe: 0.71, maxDrawdownPct: 0.7, winRatePct: 71.4, score: 10.18, tradingDays: 7, isChampion: false, rank: 2, rankText: '2/15' },
    { key: 'tech', name: '科技组合', cumulativeReturnPct: 4.23, sharpe: 0.8, maxDrawdownPct: 0.65, winRatePct: 57.1, score: 9.79, tradingDays: 7, isChampion: false, rank: 3, rankText: '3/15' },
    { key: 'aggressive_v3', name: '行业分散轮动版', cumulativeReturnPct: 5.24, sharpe: 0.5, maxDrawdownPct: 1.26, winRatePct: 57.1, score: 9.74, tradingDays: 7, isChampion: false, rank: 4, rankText: '4/15' },
    { key: 'bluechip', name: '蓝筹组合', cumulativeReturnPct: 3.54, sharpe: 0.81, maxDrawdownPct: 0.53, winRatePct: 57.1, score: 9.4, tradingDays: 7, isChampion: false, rank: 5, rankText: '5/15' },
  ],
  strategyTotal: 15,
  nav: {
    dates: strategyNavDates,
    series: [
      {
        key: 'nav_static_nale',
        label: '静态 NALE',
        color: '#3D87E8',
        returnPct: 157.32,
        series: [-0.07, 3.57, -0.78, -0.23, 2.24, 35.23, 58.58, 76.47, 71.22, 96.27, 92.37, 124.63,
                 121.66, 144.14, 134.71, 147.57, 137.66, 115.35, 118.89, 140.51, 158.59, 154.89, 157.32],
      },
      {
        key: 'nav_temporal_nale_fixed',
        label: '时序 NALE',
        color: '#26A17F',
        returnPct: 147.83,
        series: [-0.07, 2.3, -1.49, -1.57, 1.81, 36.35, 61.91, 79.26, 75.67, 99.04, 94.52, 122.4,
                 123.42, 148.24, 133.66, 143.35, 130.37, 106.87, 112.92, 133.88, 149.2, 148.31, 147.83],
      },
      {
        key: 'nav_dynamic_alpha_tnale',
        label: '动态 Alpha',
        color: '#E9A93B',
        returnPct: 169.16,
        series: [-0.07, 5.7, 2.97, 2.06, 7.84, 43.84, 66.99, 76.0, 67.69, 90.41, 90.3, 117.62,
                 123.55, 148.68, 136.32, 151.7, 138.9, 120.66, 129.98, 154.31, 170.32, 171.09, 169.16],
      },
      {
        key: 'nav_csi300_benchmark',
        label: '沪深300',
        color: '#A9B4C2',
        returnPct: 56.91,
        series: [0.0, 0.08, -1.8, -3.85, -1.04, 24.15, 32.63, 38.31, 33.96, 46.96, 43.98, 58.19,
                 59.2, 70.93, 59.84, 64.65, 57.98, 46.24, 45.65, 53.57, 60.6, 57.41, 56.91],
      },
    ],
  },
  correlation: {
    labels: ['静态 NALE', '时序 NALE', '动态 Alpha', '沪深300'],
    matrix: [
      [1.0, 0.9758, 0.9387, 0.9263],
      [0.9758, 1.0, 0.9423, 0.933],
      [0.9387, 0.9423, 1.0, 0.9291],
      [0.9263, 0.933, 0.9291, 1.0],
    ],
  },
}

/* ------------------------------------------------------------------ 07 学术因子与计量定价 */

export const academicData: AcademicEconometricsData = {
  famaMacBeth: [
    { name: 'MKT (市场风险溢价)', beta: 0.42, tStat: 4.85, pValue: '< 0.001', interpretation: '显著低 Beta 防守稳健属性' },
    { name: 'SMB (规模因子)', beta: -0.31, tStat: -3.12, pValue: '0.002', interpretation: '大盘蓝筹龙头偏好，避开小微盘暴雷' },
    { name: 'HML (价值因子)', beta: 0.58, tStat: 5.21, pValue: '< 0.001', interpretation: '高股息深度价值倾斜' },
    { name: 'MOM (Carhart动量)', beta: 0.14, tStat: 1.82, pValue: '0.069', interpretation: '中低频温和动量跟踪' },
  ],
  csmarMapping: [
    { variable: '无风险利率 (Rf)', openSource: '中国1年期国债', windField: 'cn_bond_1y', csmarField: 'sz_rf_rate / TRD_Nrrate' },
    { variable: '市场溢价 (MKT)', openSource: '沪深300日超额', windField: '000300.SH - rf', csmarField: 'FF_MKT_Daily' },
    { variable: '规模因式 (SMB)', openSource: '小市值减大市值', windField: 'stock_daily_mv', csmarField: 'FF_SMB_Daily' },
    { variable: '价值因式 (HML)', openSource: '高PB减低PB', windField: 'stock_daily_pb', csmarField: 'FF_HML_Daily' },
    { variable: '财务勾稽验证', openSource: '资产负债表附注', windField: 'WIND_Prepay/Invent', csmarField: 'FS_Combas_Prepayment' },
  ],
  rankIc: [
    { horizon: 'T+5 (短期冲击)', staticIc: 0.0280, temporalIc: 0.0206, icIr: 0.077, harveyLiuT: 0.45, improvement: '-26.4%' },
    { horizon: 'T+10 (波段传导)', staticIc: 0.0481, temporalIc: 0.0477, icIr: 0.198, harveyLiuT: 1.16, improvement: '-0.7%' },
    { horizon: 'T+15 (产业链时滞)', staticIc: 0.0294, temporalIc: 0.0334, icIr: 0.136, harveyLiuT: 0.79, improvement: '+13.5%', isHighlight: true },
    { horizon: 'T+20 (衰减吸收)', staticIc: 0.0162, temporalIc: 0.0159, icIr: 0.062, harveyLiuT: 0.36, improvement: '-1.7%' },
  ],
  naleTopology: {
    labels: ['长江电力', '三峡能源', '黄金ETF', '深科技', '宁德时代', '银华日利'],
    matrix: [
      [1.00, 0.72, 0.15, 0.12, 0.18, 0.02],
      [0.68, 1.00, 0.18, 0.14, 0.35, 0.02],
      [0.12, 0.10, 1.00, 0.08, -0.05, 0.05],
      [0.15, 0.18, 0.10, 1.00, 0.42, 0.01],
      [0.22, 0.41, -0.08, 0.38, 1.00, 0.01],
      [0.01, 0.01, 0.02, 0.01, 0.01, 1.00],
    ],
  },
  citation: {
    paperTitle: 'Rainbow-FinGPT v2: Inclusive Pension Finance via Temporal-NALE and Asymmetric Downside Risk Parity',
    paperUrl: 'papers/Rainbow_FinGPT_v2_Paper.html',
    bibtex: `@article{rainbow_fingpt2026,
  title   = {Rainbow-FinGPT v2: Inclusive Pension Finance via Temporal-NALE and Asymmetric Downside Risk Parity},
  author  = {Rainbow Quantitative Research Team},
  journal = {Computational Economics and Financial Engineering},
  year    = {2026},
  volume  = {14},
  pages   = {102--128}
}`,
  },
  notes: {
    spilloverCapture: '产业链溢出事件捕获：共计检验 390 次冲击事件，Temporal-NALE 命中率达 46.9%（较传统静态模型提升 +6.7%，p < 0.05）。',
    factorHalfLife: '因式半衰期：τ₁/₂ = 18.4 天（λ = 0.0377，拟合优度 R² = 0.892），因子拥挤度指标 HHI = 0.142（处于安全无拥挤区间）。',
    placeboTest: 'Placebo 蒙特卡洛洗牌检验：100 次随机打乱拓扑边，统计量 Z = 2.45 ≥ 1.96 (p = 0.019 < 0.05)，显著拒绝无序网络假设。',
    trendGate: 'Trend Gate™ 趋势门控：全标的处于 MA20 趋势保护带上方，未触发 C 浪惩罚。',
  },
}
