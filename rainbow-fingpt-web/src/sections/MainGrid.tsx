import { Container } from '@/components/layout/PageShell'
import AllocationPanel from './AllocationPanel'
import EquityCurvePanel from './EquityCurvePanel'
import type { AllocationSegment, CashNoteData, EquityCurveData } from '@/types'

/**
 * 03 + 04 主内容区两栏
 * 设计稿画布（≥1214）：759 + 18 + 401，与设计稿 1:1
 * 平板（1024–1213）：等比 rail（1.9 : 1）
 * 移动（<1024）：单列，主内容在前、侧栏在后
 *
 * 数据由 App 统一从 /api/v1/homepage 取好后下传；
 * 不传时两个面板回退到各自的 mock 快照，保证离线也能渲染。
 */
export default function MainGrid({
  equityCurve,
  allocation,
  cashNote,
}: {
  equityCurve?: EquityCurveData
  allocation?: AllocationSegment[]
  cashNote?: CashNoteData
}) {
  return (
    <Container className="mt-[39px]">
      <div className="grid grid-cols-1 gap-[18px] lg:grid-cols-rail desk:grid-cols-main">
        <EquityCurvePanel data={equityCurve} />
        <AllocationPanel segments={allocation} cashNote={cashNote} />
      </div>
    </Container>
  )
}
