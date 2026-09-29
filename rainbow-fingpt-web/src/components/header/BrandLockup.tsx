import type { BrandConfig } from '@/types'

/** 品牌区：Logo 52×60 + 产品名（21/800）+ 竖线 + 中文名 + 副标题（13/#8B95A3） */
export default function BrandLockup({ brand }: { brand: BrandConfig }) {
  return (
    <a href="/" className="flex shrink-0 items-center gap-3">
      <img src={brand.logo} alt="" width={52} height={60} className="h-[60px] w-[52px] object-contain" />
      <div className="min-w-0">
        <div className="flex items-center gap-2.5 whitespace-nowrap text-[21px] font-extrabold leading-6 text-ink-900 max-sm:text-[17px]">
          <span>{brand.name}</span>
          <span className="hidden text-[19px] font-normal text-[#C9D1DA] sm:inline">|</span>
          <span className="hidden sm:inline">{brand.product}</span>
        </div>
        <p className="mt-2 hidden whitespace-nowrap text-[13px] tracking-[.4px] text-[#8B95A3] lg:block">
          {brand.tagline}
        </p>
      </div>
    </a>
  )
}
