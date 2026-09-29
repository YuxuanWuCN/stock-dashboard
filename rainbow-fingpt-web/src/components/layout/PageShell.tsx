import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

/**
 * Container —— 全站唯一的水平栅格。
 * 设计稿画布 1214px，两侧各 18px 安全边距，内容宽 1178px。
 * 因此容器最大宽取 1214，内边距 18：宽屏时内容自动落成 1178 并居中，窄屏时退化为 16px 边距。
 */
export function Container({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('mx-auto w-full max-w-page px-4 sm:px-[18px]', className)}>{children}</div>
}

/**
 * PageShell —— 顶层三段式骨架：Header / Main / Footer。
 * Footer 固定在内容之后（main 占满剩余高度），不与内容重叠。
 */
export function PageShell({
  header,
  footer,
  children,
  mode,
  ...rest
}: {
  header: ReactNode
  footer: ReactNode
  children: ReactNode
  /** 展示模式，仅作为 data-mode 输出给样式与自动化测试用 */
  mode?: string
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className="flex min-h-screen flex-col bg-page" data-mode={mode} {...rest}>
      {header}
      <main className="flex-1">{children}</main>
      {footer}
    </div>
  )
}

/**
 * SectionStack —— 区块纵向节奏。
 * 设计稿实测间距：Hero→两栏 39px，两栏→产业链 20px，产业链→研报 32px。
 * 每个区块自带自己的 Container，因此这里只管纵向间距，不再包一层水平栅格。
 */
export function SectionStack({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('flex flex-col pb-7', className)}>{children}</div>
}
