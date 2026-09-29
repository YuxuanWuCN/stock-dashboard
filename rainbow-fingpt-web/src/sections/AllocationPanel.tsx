import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import SectionCard from '@/components/layout/SectionCard'
import SectionHeader from '@/components/ui/SectionHeader'
import DonutChart from '@/components/charts/DonutChart'
import { BulbIcon, OrgIcon } from '@/components/icons'
import { allocationData, cashNoteData } from '@/data/mock'
import type { AllocationSegment, CashNoteData } from '@/types'

/**
 * 04 右栏 · 401 × 386
 * 结构：标题 → 环形图 185（环宽 32）+ 图例（行距 46）→ 现金说明面板 356 × 108
 *
 * 交互态：
 * - 图例 hover / focus 高亮对应环段，点击锁定
 * - 现金面板 hover 加深底色、active 压暗、disabled 整体禁用
 * - 展开后逐条列出补充说明（grid-rows 过渡，不跳变）
 */
export default function AllocationPanel({
  segments = allocationData,
  cashNote = cashNoteData,
  disabled = false,
}: {
  segments?: AllocationSegment[]
  cashNote?: CashNoteData
  disabled?: boolean
}) {
  const [hovered, setHovered] = useState<string | null>(null)
  const [locked, setLocked] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const activeKey = locked ?? hovered

  return (
    <SectionCard as="aside" padded={false} className="flex min-h-[386px] flex-col px-[22px] pb-[26px] pt-3">
      <SectionHeader icon={<OrgIcon size={24} />} title="稳健资产配置比例" tip="按风险平价模型给出的三类资产权重" />

      <div className="mt-5 flex flex-1 flex-col gap-4 sm:flex-row sm:items-center">
        <DonutChart segments={segments} activeKey={activeKey} className="w-[190px] shrink-0" />
        {/* 真实组合有 5 只持仓 + 现金共 6 段，行距按段数自适应，避免侧栏被撑得过高 */}
        <ul className={cn('flex flex-1 flex-col', segments.length > 3 ? 'gap-[12px]' : 'gap-[26px]')}>
          {segments.map((seg) => (
            <LegendRow
              key={seg.key}
              segment={seg}
              disabled={disabled}
              active={activeKey === seg.key}
              locked={locked === seg.key}
              onHover={setHovered}
              onToggle={() => setLocked((v) => (v === seg.key ? null : seg.key))}
            />
          ))}
        </ul>
      </div>

      {/* 现金说明面板 */}
      <div
        className={cn(
          'rounded-chip bg-tech-50 p-4 transition-colors duration-150',
          !disabled && 'hover:bg-[#EDF4FE]',
        )}
      >
        <button
          type="button"
          aria-expanded={open}
          disabled={disabled}
          onClick={() => setOpen((v) => !v)}
          className={cn(
            'flex w-full items-start gap-3 text-left transition-opacity duration-150',
            'enabled:active:opacity-70',
            'disabled:cursor-not-allowed disabled:opacity-45',
          )}
        >
          <BulbIcon size={26} color="#3D87E8" className="mt-0.5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-[14px] font-extrabold text-tech-600 lg:text-[15px] desk:text-[15.5px]">{cashNote.title}</div>
            <p className="t-body mt-2 leading-[1.75] text-[#63788F]">{cashNote.body}</p>
          </div>
          <ChevronRight
            className={cn('mt-1 h-5 w-5 shrink-0 text-[#A8BDD4] transition-transform duration-200', open && 'rotate-90')}
          />
        </button>

        <div className={cn('grid transition-all duration-200', open ? 'mt-3 grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}>
          <ul className="space-y-1.5 overflow-hidden text-[12px] leading-[1.7] text-[#63788F] desk:text-[12.5px]">
            {cashNote.details.map((d) => (
              <li key={d} className="flex gap-2">
                <i className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-[#9EC1DD]" />
                <span>{d}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </SectionCard>
  )
}

function LegendRow({
  segment,
  active,
  locked,
  disabled,
  onHover,
  onToggle,
}: {
  segment: AllocationSegment
  active: boolean
  locked: boolean
  disabled: boolean
  onHover: (key: string | null) => void
  onToggle: () => void
}) {
  return (
    <li>
      <button
        type="button"
        aria-pressed={locked}
        disabled={disabled}
        onMouseEnter={() => onHover(segment.key)}
        onMouseLeave={() => onHover(null)}
        onFocus={() => onHover(segment.key)}
        onBlur={() => onHover(null)}
        onClick={onToggle}
        className={cn(
          'flex w-full items-center gap-2.5 rounded-lg px-1.5 py-1 transition-colors duration-150',
          'enabled:hover:bg-chip enabled:active:bg-line',
          'disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent',
          active && 'bg-chip',
        )}
      >
        <i
          className="h-3 w-3 shrink-0 rounded-full transition-transform duration-150"
          style={{ background: segment.color, transform: active ? 'scale(1.15)' : undefined }}
        />
        <b className="t-label min-w-0 flex-1 truncate text-left font-medium text-ink-800 lg:text-[13px]">{segment.name}</b>
        <em className="num text-[15px] font-extrabold not-italic text-ink-900 lg:text-[16px] desk:text-[17px]">
          {segment.weight}%
        </em>
      </button>
    </li>
  )
}
