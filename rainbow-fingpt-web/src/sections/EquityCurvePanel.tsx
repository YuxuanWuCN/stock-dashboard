import { useState } from 'react'
import { cn } from '@/lib/cn'
import SectionCard from '@/components/layout/SectionCard'
import SectionHeader from '@/components/ui/SectionHeader'
import EquityCurveChart, { type SeriesKey } from '@/components/charts/EquityCurveChart'
import { BoltIcon, ShieldIcon, TreeIcon } from '@/components/icons'
import { equityCurveData } from '@/data/mock'
import type { EquityCurveData } from '@/types'

/**
 * 03 左栏 · 759 × 384
 * 结构：标题组 + 图例（右上）→ 收益曲线（709 × 208）→ 三条价值点（211 × 68，间距 33）
 *
 * 交互态：
 * - 图例 hover 高亮对应曲线，点击锁定（再次点击取消）
 * - 图例 disabled 时不可交互，同时曲线不响应
 * - 价值点 hover 由浅灰底转白底 + 描边
 */
export default function EquityCurvePanel({ data = equityCurveData }: { data?: EquityCurveData }) {
  const [locked, setLocked] = useState<SeriesKey | null>(null)
  const [hovered, setHovered] = useState<SeriesKey | null>(null)
  const highlight = locked ?? hovered

  return (
    <SectionCard className="flex min-h-[384px] flex-col px-[30px] pb-6 pt-2">
      <SectionHeader
        className="h-11"
        icon={<TreeIcon size={26} />}
        title="安心增长"
        subtitle="绝对收益曲线"
        tip="组合相对沪深300的同期超额收益"
        right={
          <div className="hidden gap-6 sm:flex">
            <LegendButton
              series="portfolio"
              label={data.portfolio.name}
              value={data.portfolio.returnLabel}
              valueClass="text-gold-line"
              active={highlight === 'portfolio'}
              locked={locked === 'portfolio'}
              onHover={setHovered}
              onToggle={() => setLocked((v) => (v === 'portfolio' ? null : 'portfolio'))}
            />
            <LegendButton
              series="benchmark"
              label={data.benchmark.name}
              value={data.benchmark.returnLabel}
              valueClass="text-ink-500"
              muted
              active={highlight === 'benchmark'}
              locked={locked === 'benchmark'}
              onHover={setHovered}
              onToggle={() => setLocked((v) => (v === 'benchmark' ? null : 'benchmark'))}
            />
          </div>
        }
      />

      <div className="mt-2">
        <EquityCurveChart
          dates={data.dates}
          portfolio={data.portfolio.series}
          benchmark={data.benchmark.series}
          highlight={highlight}
        />
      </div>

      <div className="mt-auto grid grid-cols-1 gap-3 pt-4 sm:grid-cols-3 sm:gap-[33px]">
        <SeedChip tone="green" name="无需盯盘" desc="专业团队与AI双重守护" />
        <SeedChip tone="blue" name="自动防御大跌" desc="智能识别风险，提前规避" />
        <SeedChip tone="green" name="零未来函数实测" desc="回测严格，数据真实可靠" />
      </div>
    </SectionCard>
  )
}

/** 图例按钮：hover 预高亮、点击锁定、disabled 全禁用 */
function LegendButton({
  series,
  label,
  value,
  valueClass,
  muted = false,
  active,
  locked,
  disabled = false,
  onHover,
  onToggle,
}: {
  series: SeriesKey
  label: string
  value: string
  valueClass: string
  muted?: boolean
  active: boolean
  locked: boolean
  disabled?: boolean
  onHover: (s: SeriesKey | null) => void
  onToggle: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={locked}
      disabled={disabled}
      onMouseEnter={() => onHover(series)}
      onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(series)}
      onBlur={() => onHover(null)}
      onClick={onToggle}
      className={cn(
        'flex max-w-[190px] items-start gap-2 rounded-lg px-1.5 py-0 text-left transition-colors duration-150',
        'enabled:hover:bg-chip enabled:active:bg-line',
        'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
        locked && 'bg-chip',
      )}
    >
      {muted ? (
        <i className="mt-2 w-5 shrink-0 border-t-2 border-dashed border-[#A9B4C2]" />
      ) : (
        <i className="mt-[3px] h-3 w-3 shrink-0 rounded-full bg-gold-line" />
      )}
      <div className="min-w-0">
        <b className="t-label block truncate font-semibold leading-[19px] text-ink-800">{label}</b>
        <em className={cn('num mt-[3px] block text-[13px] font-extrabold not-italic leading-[22px] lg:text-[14px] desk:text-[15px]', valueClass)}>
          {value}
        </em>
      </div>
    </button>
  )
}

/** 价值点胶囊：211 × 68；hover 抬升，active 压暗 */
function SeedChip({ tone, name, desc }: { tone: 'green' | 'blue'; name: string; desc: string }) {
  return (
    <div
      className={cn(
        'flex h-[68px] items-center gap-3 rounded-chip bg-chip px-3.5 transition-all duration-150',
        'hover:-translate-y-px hover:bg-white hover:shadow-card hover:ring-1 hover:ring-line',
        'active:translate-y-0 active:bg-line',
      )}
    >
      {tone === 'green' ? <ShieldIcon size={26} color="#26A17F" /> : <BoltIcon size={26} color="#3D87E8" />}
      <div className="min-w-0">
        <div className={cn('t-item-title truncate', tone === 'green' ? 'text-brand' : 'text-tech')}>{name}</div>
        <div className="t-item-desc mt-1 truncate">{desc}</div>
      </div>
    </div>
  )
}
