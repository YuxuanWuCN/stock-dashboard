import { cn } from '@/lib/cn'
import type { StrategyNavSeries } from '@/types'

const W = 380
const H = 132
const PL = 42
const PR = 14
const PT = 12
const PB = 26

/** 设计稿的 7 个 X 轴刻度下标（对应 23 个采样点） */
const X_LABEL_INDEX = [0, 3, 6, 9, 12, 16, 22]

/** 候选刻度步长；选第一个能让纵轴刻度不超过 4 档的 */
const TICK_STEPS = [10, 20, 25, 50, 100, 200, 500, 1000]

/**
 * 策略净值走势：多条策略 / 基准的累计收益率折线，纵轴按数据自适应。
 *
 * 与 EquityCurveChart 同一套纯 SVG 画法，
 * 不引入图表库，保证与设计稿的网格、轴位、字重一致。
 */
export default function StrategyNavChart({
  dates,
  series,
  className,
}: {
  dates: string[]
  series: StrategyNavSeries[]
  className?: string
}) {
  const n = dates.length
  const values = series.flatMap((item) => item.series)

  if (n < 2 || values.length === 0) {
    return (
      <div className={cn('t-body flex h-[132px] items-center justify-center text-ink-400', className)}>
        暂无策略净值数据
      </div>
    )
  }

  const rawMax = Math.max(...values, 0)
  const rawMin = Math.min(...values, 0)

  let step = TICK_STEPS[TICK_STEPS.length - 1]
  let yMax = Math.ceil(rawMax / step) * step
  let yMin = Math.floor(rawMin / step) * step
  for (const candidate of TICK_STEPS) {
    const hi = Math.max(Math.ceil(rawMax / candidate) * candidate, candidate)
    const lo = Math.min(Math.floor(rawMin / candidate) * candidate, 0)
    if ((hi - lo) / candidate <= 4) {
      step = candidate
      yMax = hi
      yMin = lo
      break
    }
  }
  if (yMax === yMin) {
    yMax = yMin + step
  }

  const ticks: number[] = []
  for (let value = yMax; value >= yMin - 1e-9; value -= step) {
    ticks.push(Number(value.toFixed(2)))
  }

  const x = (index: number) => PL + (index * (W - PL - PR)) / (n - 1)
  const y = (value: number) => PT + ((yMax - value) / (yMax - yMin)) * (H - PT - PB)
  const path = (points: number[]) =>
    'M' + points.map((value, index) => `${x(index).toFixed(1)} ${y(value).toFixed(1)}`).join(' L')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={cn('block h-auto w-full', className)}
      role="img"
      aria-label="策略净值走势对比"
    >
      {ticks.map((value) => (
        <g key={value}>
          <line x1={PL} y1={y(value)} x2={W - PR} y2={y(value)} stroke="#EFF3F7" />
          <text x={PL - 6} y={y(value) + 4} fontSize={11} fill="#98A2B2" textAnchor="end" className="num-mono">
            {value}%
          </text>
        </g>
      ))}
      {X_LABEL_INDEX.map((index) => (
        <text
          key={index}
          x={x(Math.min(index, n - 1))}
          y={H - 6}
          fontSize={11}
          fill="#98A2B2"
          textAnchor="middle"
        >
          {dates[index] ?? ''}
        </text>
      ))}
      {series.map((item) => (
        <g key={item.key}>
          <path
            d={path(item.series)}
            fill="none"
            stroke={item.color}
            strokeWidth={2.2}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle
            cx={x(item.series.length - 1)}
            cy={y(item.series[item.series.length - 1])}
            r={3.6}
            fill={item.color}
          />
        </g>
      ))}
    </svg>
  )
}
