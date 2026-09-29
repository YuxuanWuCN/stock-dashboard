import { cn } from '@/lib/cn'
import HelpTip from '@/components/ui/HelpTip'
import HealthGauge from './HealthGauge'
import type { HealthGaugeData } from '@/types'

/**
 * 晴雨表浮层卡：294 × 155。
 * ≥xl 时贴着指标板右侧浮在 Hero 上；窄屏降级为普通卡片，跟在指标板下方。
 */
export default function HealthGaugeCard({ data, className }: { data: HealthGaugeData; className?: string }) {
  return (
    <div className={cn('rounded-[14px] bg-white/95 px-3 pb-2 pt-2 shadow-float desk:w-[294px] desk:shrink-0', className)}>
      <div className="flex items-center justify-center text-[13.5px] font-bold leading-5 text-ink-900 lg:text-[14px] desk:text-[15px]">
        {data.title}
        {data.tip && <HelpTip label={data.tip} />}
      </div>
      {/* 卡片总高锁定 155：8 + 20 + 2 + 78 + 18 + 5 + 16 + 8 */}
      <HealthGauge percent={data.percent} className="mx-auto mt-0.5 h-[78px] w-[159px]" />
      <div className="text-center text-[14px] font-extrabold leading-[18px] text-ink-900 lg:text-[15px] desk:text-[16px]">{data.level}</div>
      <div className="mt-[5px] text-center text-[11.5px] leading-4 text-ink-600 lg:text-[12px] desk:text-[12.5px]">{data.desc}</div>
    </div>
  )
}
