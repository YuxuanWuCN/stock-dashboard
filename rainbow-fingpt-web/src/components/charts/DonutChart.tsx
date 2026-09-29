import { cn } from '@/lib/cn'
import type { AllocationSegment } from '@/types'

const SIZE = 190
const C = SIZE / 2
const R = 76.5 // 环中线半径
const SW = 32 // 环宽
const GAP_DEG = 0.6 // 分段之间的视觉缝隙

/**
 * 资产配置环形图：从 12 点顺时针，绿 35% → 蓝 25% → 橙 40%。
 * 纯 SVG 实现；hover / active 的环段加粗，其余降到 35% 不透明度。
 */
export default function DonutChart({
  segments,
  activeKey = null,
  centerText = ['风险平价', '配置方案'],
  className,
}: {
  segments: AllocationSegment[]
  activeKey?: string | null
  centerText?: [string, string]
  className?: string
}) {
  const circ = 2 * Math.PI * R
  let offset = 0

  return (
    <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className={cn('block', className)} role="img" aria-label="资产配置比例环形图">
      {segments.map((seg) => {
        const len = (circ * seg.weight) / 100 - SW * (GAP_DEG / 10)
        const dash = `${len} ${circ - len}`
        const dashOffset = -offset
        offset += (circ * seg.weight) / 100
        const isActive = activeKey === seg.key
        const dimmed = activeKey !== null && !isActive
        return (
          <circle
            key={seg.key}
            cx={C}
            cy={C}
            r={R}
            fill="none"
            stroke={seg.color}
            strokeWidth={isActive ? SW + 6 : SW}
            strokeDasharray={dash}
            strokeDashoffset={dashOffset}
            transform={`rotate(-90 ${C} ${C})`}
            opacity={dimmed ? 0.35 : 1}
            className="transition-[stroke-width,opacity] duration-200"
          />
        )
      })}
      <text x={C} y={C - 6} fontSize={13} fontWeight={700} fill="#43536B" textAnchor="middle">
        {centerText[0]}
      </text>
      <text x={C} y={C + 12} fontSize={13} fontWeight={700} fill="#43536B" textAnchor="middle">
        {centerText[1]}
      </text>
    </svg>
  )
}
