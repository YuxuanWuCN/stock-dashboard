import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Container } from '@/components/layout/PageShell'
import { ArrowUpCircleIcon, BellIcon, ShieldIcon } from '@/components/icons'
import { TONE_CARD_HOVER, TONE_FILL, TONE_TEXT } from '@/lib/tone'
import { riskEvents } from '@/data/mock'
import type { RiskEvent } from '@/types'

/**
 * 05 产业链避险小卫士 · 1178 × 140
 * 一条标题行（33px）+ 三张等宽事件卡（364 × 88，间距 24）。
 *
 * 交互态：卡片 hover 抬升 + 语义色描边，active 压回，disabled 降透明度且不可点。
 * 长文自动两行截断（line-clamp-2），标题单行截断。
 */
export default function RiskRadarSection({ events = riskEvents }: { events?: RiskEvent[] }) {
  return (
    <Container className="mt-5">
      <section className="rounded-card border border-line bg-white px-[18px] pb-3 pt-[7px] shadow-card">
        <div className="flex h-[33px] items-center gap-2.5">
          <BellIcon size={23} />
          <h2 className="t-section-title">产业链避险小卫士</h2>
          <span className="t-section-sub ml-0.5 truncate">基于 NALE 图算法的产业链风险传导监测</span>
          <button
            type="button"
            className="ml-auto flex shrink-0 items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[13.5px] font-semibold text-tech transition-colors duration-150 enabled:hover:bg-tech-50 enabled:active:bg-[#E4EFFD] disabled:cursor-not-allowed disabled:opacity-40"
          >
            查看更多
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {events.map((e) => (
            <EventCard key={e.id} event={e} />
          ))}
        </div>
      </section>
    </Container>
  )
}

function EventCard({ event }: { event: RiskEvent }) {
  const { tone, icon, title, timeAgo, content, disabled = false } = event
  return (
    <button
      type="button"
      disabled={disabled}
      className={cn(
        'group h-[88px] overflow-hidden rounded-chip border border-line bg-white px-4 pb-2 pt-2 text-left transition-all duration-150',
        TONE_CARD_HOVER[tone],
        'enabled:hover:-translate-y-px enabled:hover:shadow-card enabled:active:translate-y-0 enabled:active:bg-page',
        'disabled:cursor-not-allowed disabled:opacity-45',
      )}
    >
      <div className="flex h-6 items-center gap-2.5">
        {icon === 'arrowUp' ? (
          <ArrowUpCircleIcon size={26} color="#6DA6F2" className="shrink-0" />
        ) : (
          <ShieldIcon size={26} color={TONE_FILL[tone]} className="shrink-0" />
        )}
        <b className={cn('t-item-title min-w-0 truncate font-extrabold', TONE_TEXT[tone])}>{title}</b>
        <span className="num ml-auto text-[11.5px] text-ink-400 desk:text-[12.5px]">{timeAgo}</span>
      </div>
      <p className={cn('t-body mt-1 line-clamp-2 leading-[1.6] transition-colors duration-150', !disabled && 'group-hover:text-ink-700')}>
        {content}
      </p>
    </button>
  )
}
