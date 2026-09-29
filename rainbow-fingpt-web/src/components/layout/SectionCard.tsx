import type { ElementType, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

type SectionCardProps = HTMLAttributes<HTMLElement> & {
  as?: ElementType
  padded?: boolean
  children: ReactNode
}

/**
 * SectionCard —— 全站唯一的卡片语言：白底 + 1px #EDF1F5 描边 + 统一阴影 + 16px 圆角。
 * 禁止在业务组件里另起一套边框/阴影，否则页面会出现“两种卡片”。
 */
export default function SectionCard({
  as: Tag = 'section',
  padded = true,
  className,
  children,
  ...rest
}: SectionCardProps) {
  return (
    <Tag className={cn('rounded-card border border-line bg-white shadow-card', padded && 'p-5', className)} {...rest}>
      {children}
    </Tag>
  )
}
