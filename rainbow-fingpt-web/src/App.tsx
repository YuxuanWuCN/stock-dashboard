import { useState } from 'react'
import { PageShell, SectionStack } from '@/components/layout/PageShell'
import ExpertModeSection from '@/sections/ExpertModeSection'
import Footer from '@/sections/Footer'
import Header from '@/sections/Header'
import HeroSection from '@/sections/HeroSection'
import MainGrid from '@/sections/MainGrid'
import RiskRadarSection from '@/sections/RiskRadarSection'
import { headerData, heroData } from '@/data/mock'
import { useHomepage } from '@/hooks/useHomepage'
import { LEGACY_HOME_URL } from '@/services/api'
import type { ViewMode } from '@/types'

/**
 * 顶层布局：Header / Main / Footer 三段式。
 * Main 内部顺序即设计稿的阅读顺序：Hero → 两栏 → 事件流 → 专业模式。
 *
 * 数据来源：一次 GET /api/v1/homepage 拿到 02–06 五个区块的视图模型；
 * 接口不可用时 useHomepage 自动回退到 mock 快照，页面不会白屏。
 */
export default function App() {
  const [mode, setMode] = useState<ViewMode>('retail')
  const [expertOpen, setExpertOpen] = useState(false)
  const { data } = useHomepage()

  /**
   * 顶部模式切换器的两条分支：
   * - 普惠理财通模式：本页内视图，不跳转；
   * - 机构量化研报模式：跳转到旧版看板（站点根路径）。
   *
   * 注意：这里**不再联动**下方的 06 研报面板 —— 该面板是独立折叠区，
   * 只由用户点击标题条控制，跳转前不会因为切换模式而自动展开/收起。
   */
  const handleModeChange = (next: ViewMode) => {
    if (next === 'expert') {
      window.location.href = LEGACY_HOME_URL
      return
    }
    setMode(next)
  }

  return (
    <PageShell
      mode={mode}
      header={<Header mode={mode} onModeChange={handleModeChange} data={headerData} />}
      footer={<Footer />}
    >
      <SectionStack>
        <HeroSection mode={mode} data={{ ...heroData, ...data.hero }} />
        <MainGrid equityCurve={data.equityCurve} allocation={data.allocation} cashNote={data.cashNote} />
        <RiskRadarSection events={data.riskEvents} />
        <ExpertModeSection open={expertOpen} onToggle={() => setExpertOpen((v) => !v)} data={data.expert} />
      </SectionStack>
    </PageShell>
  )
}
