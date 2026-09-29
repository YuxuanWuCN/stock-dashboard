import { HelpCircle } from 'lucide-react'

/** 标题右侧的“?”解释气泡。注：小尺寸下仅做视觉占位，悬浮解释在 Step 3 接入 Tooltip。 */
export default function HelpTip({ label }: { label: string }) {
  return (
    <button
      type="button"
      aria-label={`解释：${label}`}
      title={label}
      className="ml-1.5 inline-flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-full text-ink-300"
    >
      <HelpCircle className="h-[15px] w-[15px]" strokeWidth={1.6} />
    </button>
  )
}
