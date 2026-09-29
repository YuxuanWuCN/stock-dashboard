import type { SVGProps } from 'react'

/**
 * 实心图标集。
 * 设计稿里的盾牌 / 圆形箭头是“实心 + 白色内笔画”，Lucide 的线性图标无法直接表达，
 * 因此这几个图形用内联 SVG 复刻；其余线性图标继续用 lucide-react。
 */

export function ShieldIcon({ size = 42, color = 'currentColor', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <path d="M12 2.2 20 5v6.6c0 4.6-3.3 8.5-8 10.2-4.7-1.7-8-5.6-8-10.2V5l8-2.8Z" fill={color} />
      <path
        d="M8.4 12.1l2.5 2.5 4.7-4.9"
        stroke="#fff"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

export function RiseIcon({ size = 42, ...rest }: { size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 42 42" fill="none" aria-hidden {...rest}>
      <circle cx="21" cy="21" r="21" fill="#F4696C" />
      <path
        d="M21 31V12M13.6 19.4 21 12l7.4 7.4"
        stroke="#fff"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 蓝色闪电：Hero 价值点 / 事件卡通用 */
export function BoltIcon({ size = 26, color = '#3D87E8', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <path d="M13.4 2 5 13.4h5.2L10.6 22 19 10.6h-5.2L13.4 2Z" fill={color} />
    </svg>
  )
}

/** 圆形向上箭头：事件卡② */
export function ArrowUpCircleIcon({
  size = 26,
  color = '#6DA6F2',
  ...rest
}: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <circle cx="12" cy="12" r="10" fill={color} />
      <path
        d="M12 17V8.4M8.6 11.6 12 8.2l3.4 3.4"
        stroke="#fff"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** 三层结构图：03 绝对收益曲线标题图标 */
export function TreeIcon({ size = 26, color = '#16243C', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <rect x="9.4" y="2.4" width="5.2" height="5.2" rx="1.3" fill={color} />
      <rect x="2.6" y="16.4" width="5.2" height="5.2" rx="1.3" fill={color} />
      <rect x="16.2" y="16.4" width="5.2" height="5.2" rx="1.3" fill={color} />
      <path d="M12 7.6v4.2M5.2 16.4v-2.3h13.6v2.3" stroke={color} strokeWidth="1.5" />
    </svg>
  )
}

/** 组织关系图：04 资产配置标题图标 */
export function OrgIcon({ size = 24, color = '#16243C', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <circle cx="12" cy="5.4" r="3.1" fill={color} />
      <circle cx="5.2" cy="18.6" r="3.1" fill={color} />
      <circle cx="18.8" cy="18.6" r="3.1" fill={color} />
      <path d="M12 8.5v3.4M5.2 18.6v-3.4h13.6v3.4" stroke={color} strokeWidth="1.5" />
    </svg>
  )
}

/** 实心铃铛：05 产业链避险小卫士标题图标 */
export function BellIcon({ size = 23, color = '#16243C', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <path
        d="M12 2.6a6 6 0 0 0-6 6v4l-1.6 3.1A1 1 0 0 0 5.3 17h13.4a1 1 0 0 0 .9-1.3L18 12.6v-4a6 6 0 0 0-6-6Z"
        fill={color}
      />
      <path d="M9.6 19.4a2.6 2.6 0 0 0 4.8 0" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

/** 灯泡：04 现金说明面板 */
export function BulbIcon({ size = 26, color = '#3D87E8', ...rest }: { size?: number; color?: string } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden {...rest}>
      <path
        d="M12 2.8a6.4 6.4 0 0 0-3.7 11.6v1.9a1.3 1.3 0 0 0 1.3 1.3h4.8a1.3 1.3 0 0 0 1.3-1.3v-1.9A6.4 6.4 0 0 0 12 2.8Z"
        fill={color}
      />
      <path d="M9.9 19.6h4.2M10.6 21.8h2.8" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
