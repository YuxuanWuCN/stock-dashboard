import { useState } from 'react'
import { cn } from '@/lib/cn'

const CW = 36 // 单格宽
const CH = 21 // 单格高
const GAP = 3
const GX = 94 // 网格左边界（左侧留出行业名）
const GY = 4

/** -1 → 蓝 #3F86DE，0 → 白，+1 → 红 #E0605E */
function cellColor(v: number) {
  const t = Math.min(1, Math.abs(v))
  const base = v > 0 ? [224, 96, 94] : [74, 142, 224]
  const rgb = base.map((b) => Math.round(255 - (255 - b) * t))
  return `rgb(${rgb.join(',')})`
}

/**
 * 拓扑网络相关性矩阵：5×5 对称热力图 + 色标。
 * hover 单元格会显示「行 × 列 = 值」的读数条。
 */
export default function CorrelationHeatmap({
  labels,
  matrix,
  className,
}: {
  labels: string[]
  matrix: number[][]
  className?: string
}) {
  const [hover, setHover] = useState<[number, number] | null>(null)
  const rows = matrix.length
  const gridH = rows * CH + (rows - 1) * GAP
  const w = GX + labels.length * (CW + GAP) + 80
  // 列标签旋转 40° 后向下延伸，需预留高度（否则长标签会与底部色标挤在一起）
  const h = GY + gridH + 58

  return (
    <div className={cn('relative', className)}>
      <svg viewBox={`0 0 ${w} ${h}`} className="block h-auto w-full" role="img" aria-label="板块相关性矩阵">
        {/* 数据格 */}
        {matrix.map((row, r) =>
          row.map((v, c) => (
            <rect
              key={`${r}-${c}`}
              x={GX + c * (CW + GAP)}
              y={GY + r * (CH + GAP)}
              width={CW}
              height={CH}
              rx={2}
              fill={cellColor(v)}
              stroke={hover && hover[0] === r && hover[1] === c ? '#29394F' : 'transparent'}
              strokeWidth={1.5}
              onMouseEnter={() => setHover([r, c])}
              onMouseLeave={() => setHover(null)}
            />
          )),
        )}
        {/* 行标签 */}
        {labels.map((l, r) => (
          <text
            key={l}
            x={GX - 6}
            y={GY + r * (CH + GAP) + CH / 2 + 4}
            fontSize={12}
            fill="#5A6675"
            textAnchor="end"
          >
            {l}
          </text>
        ))}
        {/* 列标签：列宽 36px 是按设计稿的 2–4 字行业名定的，
            「静态 NALE」这类长标签横向排版会互相重叠，这里统一旋转 40° 斜排 */}
        {labels.map((l, c) => {
          const lx = GX + c * (CW + GAP) + CW / 2 + 6
          const ly = GY + gridH + 16
          return (
            <text
              key={l}
              x={lx}
              y={ly}
              fontSize={12}
              fill="#5A6675"
              textAnchor="end"
              transform={`rotate(-40 ${lx} ${ly})`}
            >
              {l}
            </text>
          )
        })}
        {/* 色标 */}
        <defs>
          <linearGradient id="corr-bar" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#E0605E" />
            <stop offset=".5" stopColor="#FFFFFF" />
            <stop offset="1" stopColor="#3F86DE" />
          </linearGradient>
        </defs>
        <rect x={w - 58} y={GY} width={13} height={gridH} rx={2} fill="url(#corr-bar)" stroke="#E4E9EF" />
        {['1.0', '0.5', '0.0', '-0.5', '-1.0'].map((t, i) => (
          <text key={t} x={w - 40} y={GY + (i * gridH) / 4 + 4} fontSize={11} fill="#98A2B2" className="num-mono">
            {t}
          </text>
        ))}
      </svg>

      {/* hover 读数 */}
      <div
        className={cn(
          'num pointer-events-none absolute right-1 top-0 rounded-md border border-line bg-white px-2 py-1 text-[11px] font-semibold text-ink-700 shadow-card transition-opacity duration-150',
          hover ? 'opacity-100' : 'opacity-0',
        )}
      >
        {hover ? `${labels[hover[0]]} × ${labels[hover[1]]} = ${matrix[hover[0]][hover[1]].toFixed(2)}` : '—'}
      </div>
    </div>
  )
}
