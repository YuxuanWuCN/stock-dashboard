import { Container } from '@/components/layout/PageShell'
import BrandLockup from '@/components/header/BrandLockup'
import ModeSwitch from '@/components/header/ModeSwitch'
import UserEntry from '@/components/header/UserEntry'
import { headerData } from '@/data/mock'
import type { HeaderData, ViewMode } from '@/types'

/**
 * 01 Header · 1178 × 90
 * 三段式：品牌区（Logo + 主副标题）/ 模式切换器 / 用户入口。
 * 注意：切换器并非绝对居中——设计稿位于 x682–1069，靠右对齐于用户入口。
 */
export default function Header({
  mode,
  onModeChange,
  data = headerData,
}: {
  mode: ViewMode
  onModeChange: (mode: ViewMode) => void
  data?: HeaderData
}) {
  return (
    <header className="bg-gradient-to-b from-[#FBFCFE] to-[#FAFBFE]">
      <Container className="flex h-[90px] items-center gap-4">
        <BrandLockup brand={data.brand} />
        <ModeSwitch
          value={mode}
          options={data.modes}
          onChange={onModeChange}
          className="ml-auto hidden shrink-0 sm:flex"
        />
        <div className="ml-auto shrink-0 sm:ml-6 md:ml-8">
          <UserEntry label={data.user.label} />
        </div>
      </Container>
    </header>
  )
}
