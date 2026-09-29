const R = 92
const CX = 106
const CY = 96
const ARC_LENGTH = Math.PI * R

/**
 * 资产健康晴雨表：只画上半圆。
 * 路径从右侧端点 (198,96) 起，经顶点到左侧端点 (14,96)，因此 dasharray 会让绿色弧从右侧开始生长。
 */
export default function HealthGauge({ percent, className }: { percent: number; className?: string }) {
  const v = Math.min(1, Math.max(0, percent))
  const d = `M${CX + R} ${CY} A${R} ${R} 0 0 0 ${CX - R} ${CY}`

  return (
    <svg viewBox="0 0 212 104" className={className} fill="none" aria-hidden>
      <path d={d} stroke="#E7EBF1" strokeWidth={13} strokeLinecap="round" />
      <path
        d={d}
        stroke="#26A17F"
        strokeWidth={13}
        strokeLinecap="round"
        strokeDasharray={`${ARC_LENGTH * v} ${ARC_LENGTH}`}
      />
      <circle cx={CX} cy={CY} r={4} fill="#B6BEC9" />
      <g transform={`translate(${CX} 66)`}>
        <circle r={13} fill="#FFC24B" />
        <g stroke="#FFC24B" strokeWidth="3.2" strokeLinecap="round">
          <path d="M0-19v-5.5M18-8l4.5-3.5M-18-8l-4.5-3.5M20 3h5.5M-20 3h-5.5" />
        </g>
      </g>
    </svg>
  )
}
