import { useState, type MouseEvent } from 'react'
import { cn } from '@/lib/cn'

const W = 709
const H = 208
const PL = 46 // 左侧留白（放 Y 轴刻度）
const PR = 26
const PT = 14
const PB = 30
const Y_MAX = 20
const Y_MIN = -20
const TICKS = [20, 10, 0, -10, -20]
/** 设计稿标注的 7 个 X 轴刻度所在的下标 */
const X_LABEL_INDEX = [0, 3, 6, 9, 12, 16, 20]

export type SeriesKey = 'portfolio' | 'benchmark'

/**
 * 绝对收益曲线：双序列折线（组合金实线 / 基准灰虚线）。
 * 纯 SVG 实现，不引入 ECharts，保证与设计稿的网格、轴位、末端标注 1:1。
 *
 * 交互态：
 * - hover 画布 → 竖向指示线 + 双数值气泡
 * - highlight 某条序列 → 另一条降到 25% 不透明度（由图例控制）
 */
export default function EquityCurveChart({
  dates,
  portfolio,
  benchmark,
  highlight = null,
  className,
}: {
  dates: string[]
  portfolio: number[]
  benchmark: number[]
  highlight?: SeriesKey | null
  className?: string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const n = dates.length
  const step = (W - PL - PR) / (n - 1)
  const x = (i: number) => PL + i * step
  const y = (v: number) => PT + ((Y_MAX - v) / (Y_MAX - Y_MIN)) * (H - PT - PB)

  const path = (s: number[]) => 'M' + s.map((v, i) => `${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' L')
  const dim = (key: SeriesKey) => (highlight && highlight !== key ? 0.25 : 1)

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * W
    if (px < PL - step / 2 || px > W - PR + step / 2) return setHover(null)
    setHover(Math.max(0, Math.min(n - 1, Math.round((px - PL) / step))))
  }

  return (
    <div className={cn('relative', className)}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="block h-auto w-full"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        role="img"
        aria-label="我们的防御组合与沪深300同期收益对比曲线"
      >
        {/* 网格 + Y 轴刻度 */}
        {TICKS.map((v) => (
          <g key={v}>
            <line x1={PL} y1={y(v)} x2={W - PR + 6} y2={y(v)} stroke="#EFF3F7" strokeWidth={1} />
            <text x={PL - 8} y={y(v) + 4} fontSize={11.5} fill="#98A2B2" textAnchor="end">
              {v}%
            </text>
          </g>
        ))}

        {/* X 轴刻度 */}
        {X_LABEL_INDEX.map((i) => (
          <text key={i} x={x(i)} y={H - 8} fontSize={11.5} fill="#98A2B2" textAnchor="middle">
            {dates[i]}
          </text>
        ))}

        {/* hover 指示线 */}
        {hover !== null && (
          <line x1={x(hover)} y1={PT - 6} x2={x(hover)} y2={H - PB + 6} stroke="#C9D6E4" strokeWidth={1} strokeDasharray="4 4" />
        )}

        {/* 组合（金实线） */}
        <path
          d={path(portfolio)}
          fill="none"
          stroke="#E9A93B"
          strokeWidth={2.4}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={dim('portfolio')}
          className="transition-opacity duration-150"
        />
        {/* 基准（灰虚线） */}
        <path
          d={path(benchmark)}
          fill="none"
          stroke="#A9B4C2"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeDasharray="6 5"
          opacity={dim('benchmark')}
          className="transition-opacity duration-150"
        />

        {/* 末端圆点 */}
        <circle cx={x(n - 1)} cy={y(portfolio[n - 1])} r={5.5} fill="#E9A93B" opacity={dim('portfolio')} />
        <circle cx={x(n - 1)} cy={y(benchmark[n - 1])} r={5.5} fill="#A9B4C2" opacity={dim('benchmark')} />

        {/* hover 数值点 */}
        {hover !== null && (
          <>
            <circle cx={x(hover)} cy={y(portfolio[hover])} r={4.5} fill="#fff" stroke="#E9A93B" strokeWidth={2.4} />
            <circle cx={x(hover)} cy={y(benchmark[hover])} r={4.5} fill="#fff" stroke="#A9B4C2" strokeWidth={2.4} />
          </>
        )}
      </svg>

      {/* 末端数值标注（用 HTML 定位，避免 SVG 文本被裁切） */}
      <span
        className="num pointer-events-none absolute text-[13px] font-bold text-gold-line transition-opacity duration-150"
        style={{ right: 34, top: `${((y(portfolio[n - 1]) - 10) / H) * 100}%`, opacity: dim('portfolio') }}
      >
        {portfolio[n - 1] > 0 ? '+' : ''}
        {portfolio[n - 1].toFixed(2)}%
      </span>
      <span
        className="num pointer-events-none absolute text-[13px] font-bold text-ink-500 transition-opacity duration-150"
        style={{ right: 28, top: `${((y(benchmark[n - 1]) + 12) / H) * 100}%`, opacity: dim('benchmark') }}
      >
        {benchmark[n - 1].toFixed(2)}%
      </span>

      {/* hover 气泡 */}
      {hover !== null && (
        <div
          className="pointer-events-none absolute z-10 -translate-x-1/2 rounded-lg border border-line bg-white px-2.5 py-2 shadow-card"
          style={{ left: `${(x(hover) / W) * 100}%`, bottom: '85%' }}
        >
          <div className="num mb-1 text-[11px] text-ink-400">{dates[hover]}</div>
          <div className="num flex items-center gap-1.5 text-[12px] font-bold text-gold-line">
            <i className="h-2 w-2 rounded-full bg-gold-line" />
            {portfolio[hover] > 0 ? '+' : ''}
            {portfolio[hover].toFixed(2)}%
          </div>
          <div className="num mt-0.5 flex items-center gap-1.5 text-[12px] font-bold text-ink-500">
            <i className="h-2 w-2 rounded-full bg-[#A9B4C2]" />
            {benchmark[hover].toFixed(2)}%
          </div>
        </div>
      )}
    </div>
  )
}
