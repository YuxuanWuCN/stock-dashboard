import { cn } from '@/lib/cn'
import { RiseIcon, ShieldIcon } from '@/components/icons'
import HelpTip from '@/components/ui/HelpTip'
import { TONE_FILL, TONE_TEXT } from '@/lib/tone'
import type { HeroMetric } from '@/types'

/**
 * 单张核心指标卡：图标 42 + 标题 16/600 + 数值 40/800 + 兜底文案 16/400。
 * 桌面端固定高 112（在 166 的指标板里垂直居中），窄屏自适应。
 */
export default function MetricCard({ metric, className }: { metric: HeroMetric; className?: string }) {
  return (
    <div className={cn('flex items-start gap-2.5 desk:h-[112px] desk:pl-[30px]', className)}>
      <span className="mt-0.5 shrink-0">
        {metric.icon === 'rise' ? (
          <RiseIcon size={42} />
        ) : (
          <ShieldIcon size={42} color={TONE_FILL[metric.tone]} />
        )}
      </span>
      <div className="min-w-0">
        <div className="flex items-center whitespace-nowrap text-[14px] font-semibold text-ink-800 lg:text-[15px] desk:text-[16px]">
          {metric.label}
          {metric.tip && <HelpTip label={metric.tip} />}
        </div>
        <div
          className={cn(
            'num mt-3.5 whitespace-nowrap tracking-[-.5px] t-metric',
            TONE_TEXT[metric.tone],
          )}
        >
          {metric.value}
        </div>
        <div className="mt-5 whitespace-nowrap text-[12.5px] text-ink-600 lg:text-[14px] desk:text-[16px]">{metric.caption}</div>
      </div>
    </div>
  )
}
