import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'
import HelpTip from './HelpTip'

/** 区块/卡片标题行：图标 24px + 主标题（20/800）+ 次标题（20/400）+ “?” + 右侧插槽 */
export default function SectionHeader({
  icon,
  title,
  subtitle,
  tip,
  right,
  className,
}: {
  icon: ReactNode
  title: string
  subtitle?: string
  tip?: string
  right?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-center gap-x-2.5 gap-y-1', className)}>
      <span className="shrink-0 text-ink-900">{icon}</span>
      <h2 className="t-card-title">{title}</h2>
      {subtitle && <span className="t-card-sub">{subtitle}</span>}
      {tip && <HelpTip label={tip} />}
      {right && <div className="ml-auto shrink-0">{right}</div>}
    </div>
  )
}
