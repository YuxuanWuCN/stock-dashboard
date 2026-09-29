import { ChevronRight, User } from 'lucide-react'

/** 用户入口：头像 22px + “我的” + 箭头；小屏只留头像 */
export default function UserEntry({ label }: { label: string }) {
  return (
    <button
      type="button"
      className="flex items-center gap-1.5 whitespace-nowrap text-[14.5px] font-medium text-ink-700 hover:text-ink-900"
    >
      <span className="flex h-[22px] w-[22px] items-center justify-center rounded-full bg-[#EDF1F6]">
        <User className="h-3.5 w-3.5 text-ink-400" strokeWidth={2.2} />
      </span>
      <span className="hidden sm:inline">{label}</span>
      <ChevronRight className="hidden h-4 w-4 text-ink-400 sm:block" />
    </button>
  )
}
