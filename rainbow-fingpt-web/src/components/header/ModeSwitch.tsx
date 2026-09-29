import { FlaskConical, ShieldCheck } from 'lucide-react'
import { cn } from '@/lib/cn'
import type { ModeOption, ViewMode } from '@/types'

/**
 * 模式切换器：受控组件。
 * 设计稿尺寸 387 × 42（内边距 3），选中档 189×36，未选中档 195×36。
 * 中屏以下收紧为「短标签」，小屏收到图标 + 两字标签，保证不换行。
 */
export default function ModeSwitch({
  value,
  options,
  onChange,
  className,
}: {
  value: ViewMode
  options: ModeOption[]
  onChange: (mode: ViewMode) => void
  className?: string
}) {
  return (
    <div
      role="tablist"
      aria-label="展示模式"
      className={cn('flex h-[42px] items-center rounded-full bg-[#ECEEF1] p-[3px]', className)}
    >
      {options.map((opt) => {
        const active = opt.id === value
        return (
          <button
            key={opt.id}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={opt.label}
            onClick={() => onChange(opt.id)}
            className={cn(
              'flex h-9 items-center justify-center gap-2 rounded-full transition-colors duration-150',
              opt.id === 'retail' ? 'w-[189px] max-lg:w-[152px] max-sm:w-[92px]' : 'w-[195px] max-lg:w-[166px] max-sm:w-[92px]',
              active
                ? 'bg-gradient-to-br from-[#31A38A] to-brand text-white shadow-[0_2px_8px_rgba(38,161,127,.32)]'
                : 'text-ink-800 hover:bg-white/70',
            )}
          >
            {opt.icon === 'shield' ? (
              <ShieldCheck className="h-5 w-5 shrink-0" strokeWidth={2} />
            ) : (
              <FlaskConical className={cn('h-5 w-5 shrink-0', !active && 'text-ink-300')} strokeWidth={1.8} />
            )}
            <span className="text-[15px] font-bold leading-tight max-lg:text-[13px]">
              <span className="max-sm:hidden">{opt.label}</span>
              <span className="hidden max-sm:inline">{opt.short ?? opt.label}</span>
              {active && opt.note && (
                <em className="hidden text-[11.5px] font-medium not-italic opacity-80 sm:block">{opt.note}</em>
              )}
            </span>
          </button>
        )
      })}
    </div>
  )
}
