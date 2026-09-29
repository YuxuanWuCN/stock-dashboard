import { ChevronUp, FlaskConical, BookOpen } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { cn } from '@/lib/cn'
import { Container } from '@/components/layout/PageShell'
import CorrelationHeatmap from '@/components/charts/CorrelationHeatmap'
import StrategyNavChart from '@/components/charts/StrategyNavChart'
import AcademicPanel from '@/components/academic/AcademicPanel'
import { expertData, academicData as defaultAcademicData } from '@/data/mock'
import type { AcademicEconometricsData, ExpertData, StrategyNavSeries, StrategyRow } from '@/types'

type ExpertTab = 'strategy' | 'academic'

/**
 * 06 机构量化研报模式 · 1178 × 274
 * 深色标题条（58px，唯一深色面）+ 白色正文（216px，三列 380 / 406 / 392）。
 *
 * 三列内容均为「策略表现」，数据来自 quantitative/latest_evolution.json 与
 * 双版本回测 daily_nav_series：
 *   策略对比表 / 策略净值走势 / 策略相关性矩阵
 *
 * 交互态：标题条 hover 提亮、active 压暗、disabled 降透明且不可折叠；
 * 折叠用 grid-rows 过渡，正文高度不跳变；表格行 hover 高亮；热力图单元格 hover 出读数。
 *
 * 注意：本区块是**独立折叠面板**，由自己的 open 状态控制，
 * 不跟随顶部「机构量化研报模式」按钮（那个按钮是跳转到旧版看板）。
 */
export default function ExpertModeSection({
  open,
  onToggle,
  data = expertData,
  academicData = defaultAcademicData,
  disabled = false,
}: {
  open: boolean
  onToggle: () => void
  data?: ExpertData
  academicData?: AcademicEconometricsData
  disabled?: boolean
}) {
  const [tab, setTab] = useState<ExpertTab>('strategy')

  const best = data.nav.series.reduce<StrategyNavSeries | null>(
    (top, item) =>
      top === null || (item.returnPct ?? Number.NEGATIVE_INFINITY) > (top.returnPct ?? Number.NEGATIVE_INFINITY)
        ? item
        : top,
    null,
  )

  return (
    <Container className="mt-8">
      <section className="overflow-hidden rounded-card shadow-[0_2px_10px_rgba(22,36,60,.10)]">
        {/* 深色标题条 */}
        <button
          type="button"
          aria-expanded={open}
          disabled={disabled}
          onClick={onToggle}
          className={cn(
            'flex h-[58px] w-full items-center gap-2.5 bg-ink-800 px-[22px] text-left text-white transition-colors duration-150',
            'enabled:hover:bg-[#32445F] enabled:active:bg-[#22304A]',
            'disabled:cursor-not-allowed disabled:opacity-70',
          )}
        >
          <FlaskConical className="h-[22px] w-[22px]" strokeWidth={1.8} />
          <h2 className="text-[17px] font-extrabold lg:text-[19px] desk:text-[20px]">机构量化研报模式</h2>
          <span className="text-[12px] text-[#B9C6D6] desk:text-[13px]">{open ? '（点击收起）' : '（点击展开）'}</span>
          <span className="ml-auto hidden text-[12px] text-[#C6D2E0] md:block desk:text-[13px]">下沉到底层硬核数据，专业指标一键查看</span>
          <ChevronUp
            className={cn('h-4 w-4 shrink-0 text-[#C6D2E0] transition-transform duration-200', !open && 'rotate-180')}
          />
        </button>

        {/* Tab 切换条 */}
        <div
          className={cn(
            'grid bg-white transition-all duration-300',
            open ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0',
          )}
        >
          <div className="overflow-hidden">
            {/* Tab 导航 */}
            <div className="flex border-b border-line bg-page">
              <TabButton active={tab === 'strategy'} onClick={() => setTab('strategy')} icon={<FlaskConical className="h-3.5 w-3.5" />}>
                策略回测表现
              </TabButton>
              <TabButton active={tab === 'academic'} onClick={() => setTab('academic')} icon={<BookOpen className="h-3.5 w-3.5" />}>
                学术因子与计量定价
              </TabButton>
            </div>

            {/* Tab 内容 */}
            {tab === 'strategy' ? (
              <div className="grid grid-cols-1 divide-y divide-line border border-t-0 border-line md:grid-cols-3 md:divide-x md:divide-y-0 desk:grid-cols-expert">
                <ExpertColumn
                  title="策略表现面板"
                  extra={
                    <span className="num-mono ml-auto text-[12.5px] font-bold text-ink-400">
                      TOP {data.strategies.length}/{data.strategyTotal}
                    </span>
                  }
                >
                  <StrategyTable rows={data.strategies} />
                </ExpertColumn>

                <ExpertColumn
                  title="策略净值走势"
                  extra={
                    best && (
                      <span className="num-mono ml-auto text-[14px] font-extrabold text-tech">
                        最优 {formatSigned(best.returnPct, 1)}
                      </span>
                    )
                  }
                >
                  <StrategyNavChart dates={data.nav.dates} series={data.nav.series} />
                  <NavLegend series={data.nav.series} />
                </ExpertColumn>

                <ExpertColumn title="策略相关性矩阵">
                  {data.correlation ? (
                    <CorrelationHeatmap labels={data.correlation.labels} matrix={data.correlation.matrix} />
                  ) : (
                    <div className="t-body flex h-[132px] items-center justify-center text-ink-400">暂无回测数据</div>
                  )}
                </ExpertColumn>
              </div>
            ) : (
              <div className="border border-t-0 border-line">
                <AcademicPanel data={academicData} />
              </div>
            )}
          </div>
        </div>
      </section>
    </Container>
  )
}

function ExpertColumn({ title, extra, children }: { title: string; extra?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col desk:h-[216px] desk:overflow-hidden">
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line bg-page px-[22px]">
        <h3 className="truncate text-[13px] font-extrabold text-ink-900 lg:text-[14px] desk:text-[14.5px]">{title}</h3>
        {extra}
      </div>
      <div className="desk:min-h-0 desk:flex-1 desk:overflow-hidden px-[22px] py-2.5">{children}</div>
    </div>
  )
}

/** 数字格式化：空值统一显示短横线，避免出现 null / NaN */
function formatSigned(value: number | null, digits = 2): string {
  if (value === null) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}%`
}

function formatNumber(value: number | null, digits = 2): string {
  return value === null ? '—' : value.toFixed(digits)
}

/** 策略对比表：四列（策略名称 / 累计收益 / 夏普 / 综合评分），冠军行高亮，行 hover 变底色 */
function StrategyTable({ rows }: { rows: StrategyRow[] }) {
  if (rows.length === 0) {
    return <div className="t-body flex h-[132px] items-center justify-center text-ink-400">暂无策略数据</div>
  }

  return (
    <table className="w-full border-collapse">
      <thead>
        <tr className="text-[11.5px] font-semibold text-ink-400 desk:text-[12.5px]">
          <th className="w-[46%] whitespace-nowrap pb-1.5 pt-1 text-left font-semibold">策略名称</th>
          <th className="whitespace-nowrap pb-1.5 pt-1 text-right font-semibold">累计收益</th>
          <th className="whitespace-nowrap pb-1.5 pr-3 pt-1 text-right font-semibold">夏普</th>
          <th className="whitespace-nowrap pb-1.5 pr-2 pt-1 text-right font-semibold">评分</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-t border-[#F2F5F9] transition-colors duration-150 hover:bg-page">
            <td className="py-[5px] pr-2 text-[13px] text-ink-700 desk:text-[14px]">
              <span className="flex items-center gap-1.5">
                {row.isChampion && (
                  <span
                    className="shrink-0 rounded-[4px] bg-brand-50 px-1 text-[10.5px] font-bold leading-[16px] text-brand"
                    title="当周冠军策略"
                  >
                    冠军
                  </span>
                )}
                <span className="truncate">{row.name}</span>
              </span>
            </td>
            <td
              className={cn(
                'num-mono py-[5px] pr-3 text-right text-[13px] font-medium desk:text-[14px]',
                (row.cumulativeReturnPct ?? 0) < 0 ? 'text-risk' : 'text-brand',
              )}
            >
              {formatSigned(row.cumulativeReturnPct)}
            </td>
            <td className="num-mono py-[5px] pr-3 text-right text-[13px] text-ink-700 desk:text-[14px]">
              {formatNumber(row.sharpe)}
            </td>
            <td className="num-mono py-[5px] pr-2 text-right text-[13px] font-semibold text-ink-900 desk:text-[14px]">
              {formatNumber(row.score)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/** 净值曲线图例：颜色点 + 策略名 + 区间收益 */
function NavLegend({ series }: { series: StrategyNavSeries[] }) {
  if (series.length === 0) return null

  return (
    <ul className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1">
      {series.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <i className="h-2 w-2 shrink-0 rounded-full" style={{ background: item.color }} />
          <span className="t-label text-ink-600">{item.label}</span>
          <em className="num text-[12px] font-bold not-italic text-ink-800">{formatSigned(item.returnPct, 1)}</em>
        </li>
      ))}
    </ul>
  )
}

/** Tab 切换按钮 */
function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-5 py-2.5 text-[13px] font-semibold transition-colors duration-150',
        active
          ? 'border-b-2 border-brand text-brand bg-white'
          : 'text-ink-500 hover:text-ink-700 hover:bg-white/60',
      )}
    >
      {icon}
      {children}
    </button>
  )
}
