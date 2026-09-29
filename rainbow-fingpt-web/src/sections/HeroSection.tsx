import { Container } from '@/components/layout/PageShell'
import HealthGaugeCard from '@/components/hero/HealthGaugeCard'
import MetricCard from '@/components/hero/MetricCard'
import { heroForMode } from '@/data/mock'
import type { HeroData, ViewMode } from '@/types'

/**
 * 02 Hero · 1178 × 293
 * 图层：暖白底 → 照片层（右下，固定 293 高）→ 照片层内部的左向渐变 → 内容。
 *
 * 两个关键约束（修的就是这两个 bug）：
 * 1. 照片层高度锁死 293 且贴右下，不随 Hero 变高而拉伸 —— 否则窄屏会把人物裁成只露头。
 * 2. 渐变画在照片层内部（而不是覆盖整个 Hero）—— 否则换个宽度渐变就和照片左缘错位，出现硬边。
 */
export default function HeroSection({ mode = 'retail', data }: { mode?: ViewMode; data?: HeroData }) {
  const hero = data ?? heroForMode(mode)

  return (
    <Container className="pt-px">
      {/* 底色只在照片左侧可见，实测为 #FAF8F1 → #F6F1E7 的暖白渐变 */}
      <section className="relative isolate overflow-hidden rounded-hero bg-[linear-gradient(96deg,#FAF8F1_0%,#FAF8F1_44%,#F8F4EC_60%,#F6F1E7_100%)]">
        {/* ① ≥desk(1214)：照片贴右下，高度锁死 293（与设计稿一致），人物全身可见 */}
        <div aria-hidden className="hero-photo-desk hidden desk:block">
          <img src={hero.backgroundImage} alt="" />
          <div className="hero-photo-desk-veil" />
        </div>

        {/* ② <desk：照片改为顶部通栏（高度与正文下移量由 index.css 统一控制） */}
        <div aria-hidden className="hero-photo-band">
          <img src={hero.backgroundImage} alt="" />
          <div className="hero-photo-band-veil" />
        </div>

        {/* 纵向节奏按设计稿实测：26 顶距 → H1 36 → 8 → 副标题 24 → 28 → 指标板 166 → 5 底距 = 293 */}
        <div className="hero-content relative flex min-h-[293px] flex-col px-5 pb-5 sm:px-[30px]">
          <h1 className="max-w-[560px] text-[23px] font-extrabold leading-8 tracking-[.2px] text-ink-900 lg:text-[26px] lg:leading-9 desk:text-[28px]">
            {hero.title}
          </h1>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <p className="text-[14px] leading-6 tracking-[.3px] text-ink-600 lg:text-[15px] desk:text-[16px]">{hero.subtitle}</p>
            {hero.modeBadge && (
              <span className="rounded-full bg-tech-50 px-2.5 py-1 text-[12.5px] font-semibold text-tech-600">
                {hero.modeBadge}
              </span>
            )}
          </div>

          {/* 指标板 + 晴雨表：≥desk(1214) 还原设计稿的并排浮层，窄屏纵向堆叠 */}
          <div className="mt-6 flex items-end desk:mt-7">
            <div className="flex w-full flex-col gap-[19px] desk:-ml-2.5 desk:flex-row desk:items-end">
              <div className="grid grid-cols-1 gap-4 rounded-chip border border-white/90 bg-white/95 p-4 shadow-float sm:grid-cols-3 sm:gap-0 desk:h-[166px] desk:w-[822px] desk:grid-cols-[269px_248px_305px] desk:items-center desk:p-0">
                {hero.metrics.map((metric, i) => (
                  <MetricCard
                    key={metric.id}
                    metric={metric}
                    className={i > 0 ? 'border-t border-[#EFF2F6] pt-4 sm:border-l sm:border-t-0 sm:py-4 sm:pl-5 desk:py-0' : 'sm:py-4 desk:py-0'}
                  />
                ))}
              </div>
              <HealthGaugeCard data={hero.gauge} />
            </div>
          </div>
        </div>
      </section>
    </Container>
  )
}
