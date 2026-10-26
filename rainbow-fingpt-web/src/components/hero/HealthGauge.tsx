import { useEffect, useState } from 'react'

const R = 92
const CX = 106
const CY = 96
const ARC_LENGTH = Math.PI * R

/**
 * 资产健康晴雨表：动态生长圆弧 + 科技雷达核心脉冲。
 */
export default function HealthGauge({ percent, className }: { percent: number; className?: string }) {
  const [animatedPercent, setAnimatedPercent] = useState(0)
  const target = Math.min(1, Math.max(0, percent))

  useEffect(() => {
    // 页面加载或百分比变化时触发缓动平滑生长
    const timeout = setTimeout(() => {
      setAnimatedPercent(target)
    }, 100)
    return () => clearTimeout(timeout)
  }, [target])

  const d = `M${CX + R} ${CY} A${R} ${R} 0 0 0 ${CX - R} ${CY}`
  // 计算指针角度：0% 在左 (-90deg), 100% 在右 (90deg)
  const angle = (animatedPercent - 0.5) * 180

  return (
    <svg viewBox="0 0 212 108" className={className} fill="none" aria-hidden>
      <defs>
        <linearGradient id="gauge-gradient" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#10B981" />
          <stop offset="60%" stopColor="#26A17F" />
          <stop offset="100%" stopColor="#38BDF8" />
        </linearGradient>
        <filter id="gauge-glow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="0" stdDeviation="3" floodColor="#10B981" floodOpacity="0.4" />
        </filter>
      </defs>

      {/* 背景底槽 */}
      <path d={d} stroke="#EAEFF5" strokeWidth={13} strokeLinecap="round" />

      {/* 动态生长能量弧 */}
      <path
        d={d}
        stroke="url(#gauge-gradient)"
        strokeWidth={13}
        strokeLinecap="round"
        filter="url(#gauge-glow)"
        style={{
          strokeDasharray: `${ARC_LENGTH}`,
          strokeDashoffset: `${ARC_LENGTH * (1 - animatedPercent)}`,
          transition: 'stroke-dashoffset 1.4s cubic-bezier(0.16, 1, 0.3, 1)',
        }}
      />

      {/* 刻度锚点 */}
      <circle cx={CX - R} cy={CY} r={2.5} fill="#94A3B8" />
      <circle cx={CX} cy={CY - R} r={2.5} fill="#94A3B8" />
      <circle cx={CX + R} cy={CY} r={2.5} fill="#94A3B8" />

      {/* 中心枢轴 */}
      <circle cx={CX} cy={CY} r={5} fill="#64748B" />
      <circle cx={CX} cy={CY} r={2} fill="#FFFFFF" />

      {/* 科技雷达中枢：带平滑旋转与呼吸光晕 */}
      <g
        transform={`translate(${CX} ${CY}) rotate(${angle})`}
        style={{ transition: 'transform 1.4s cubic-bezier(0.16, 1, 0.3, 1)' }}
      >
        {/* 指针 */}
        <line x1="0" y1="0" x2="0" y2={-R + 10} stroke="#0F172A" strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="0" cy={-R + 10} r="3.5" fill="#10B981" />
      </g>

      {/* 中心状态脉冲信标 */}
      <g transform={`translate(${CX} 68)`}>
        <circle r={10} fill="#10B981" fillOpacity="0.15" className="animate-ping" />
        <circle r={7} fill="#10B981" fillOpacity="0.25" />
        <circle r={4} fill="#10B981" />
      </g>
    </svg>
  )
}

