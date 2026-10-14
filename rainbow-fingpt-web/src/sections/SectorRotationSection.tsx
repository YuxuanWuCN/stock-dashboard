import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/cn'
import { Container } from '@/components/layout/PageShell'
import SectionHeader from '@/components/ui/SectionHeader'
import { TreeIcon } from '@/components/icons'
import { TONE_FILL, TONE_TEXT } from '@/lib/tone'
import { useSectorRotation } from '@/hooks/useSectorRotation'
import type { Tone } from '@/types'
import type { SectorRotationPayload, SectorRotationStateView, SectorRotationStatus } from '@/types/sectorRotation'

/**
 * 板块轮动决策卡（阶段5 集成）
 *
 * 设计约束：
 * - 只做展示与解释，不提供任何「一键下单」类操作；
 * - 数据诚实性优先：情绪来源与是否通过业绩门槛都要显性标注；
 * - 缺数据时展示空态与原因，不用 mock 伪造板块结论。
 */

const TREND_TONE: Record<SectorRotationStateView['sentiment_trend'], Tone> = {
  rising: 'green',
  stable: 'blue',
  declining: 'red',
}

const TREND_LABEL: Record<SectorRotationStateView['sentiment_trend'], string> = {
  rising: '上行',
  stable: '平稳',
  declining: '下沉',
}

const STATUS_BADGE: Record<SectorRotationStatus, { label: string; tone: Tone }> = {
  ok: { label: '数据正常', tone: 'green' },
  stale: { label: '数据过期', tone: 'orange' },
  missing: { label: '尚无决策产物', tone: 'blue' },
  error: { label: '数据不可用', tone: 'red' },
}

export default function SectorRotationSection() {
  const { data, status, ageTradingDays, loading, error, reload } = useSectorRotation()
  const badge = STATUS_BADGE[status === 'loading' ? 'missing' : status]

  return (
    <Container className="mt-5">
      <section className="card-surface px-[18px] pb-4 pt-[10px]">
        <SectionHeader
          icon={<TreeIcon size={24} />}
          title="板块轮动决策"
          subtitle="三板块情绪驱动的量化轮动信号"
          tip="由 docs/data/sector_rotation/latest_rotation.json 提供；代理情绪仅验证链路，不作业绩结论"
          right={
            <div className="flex items-center gap-2">
              <span className={cn('t-label rounded-chip px-2 py-0.5 font-semibold', TONE_TEXT[badge.tone])}>
                {badge.label}
                {status === 'stale' && ageTradingDays !== null ? `（${ageTradingDays} 个交易日前）` : ''}
              </span>
              <button
                type="button"
                onClick={reload}
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 t-label text-tech transition-colors duration-150 hover:bg-tech-50 active:bg-[#E4EFFD]"
              >
                <RefreshCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
                刷新
              </button>
            </div>
          }
        />

        {data === null ? (
          <p className="t-body mt-4 rounded-chip bg-page px-4 py-3 text-ink-500">
            {loading ? '正在读取板块轮动决策…' : error ?? '暂无板块轮动决策数据（每日流水线 6b 步生成后自动出现）'}
          </p>
        ) : (
          <>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
              {Object.values(data.sectors).map((st) => (
                <SectorCard key={st.sector} state={st} holding={st.sector === data.holding_sector} />
              ))}
            </div>

            <DecisionRow data={data} />

            <div className="t-label mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-ink-500">
              <span>
                数据时间：
                <b className="num font-bold text-ink-700">{data.trade_date}</b>
                <span className="num-mono">（生成 {data.generated_at}）</span>
              </span>
              <span>
                情绪来源：
                <b className={cn('num font-bold', data.report_usable ? 'text-brand' : 'text-[#D9722A]')}>
                  {data.sentiment_source}
                </b>
                {!data.report_usable && '（代理信号，禁作业绩结论）'}
              </span>
              {!data.strategy_validated && (
                <span className="text-[#D9722A]">尚未通过回测覆盖门槛，仅作决策参考</span>
              )}
            </div>

            {data.notes.length > 0 && (
              <ul className="t-body mt-2 list-disc space-y-1 pl-5 text-ink-500">
                {data.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>
    </Container>
  )
}

function SectorCard({ state, holding }: { state: SectorRotationStateView; holding: boolean }) {
  const tone = TREND_TONE[state.sentiment_trend]
  /** 分数条：[-1, 1] 映射到 0–100%，零轴居中 */
  const fillPct = Math.max(0, Math.min(100, ((state.sentiment_score + 1) / 2) * 100))

  return (
    <div
      className={cn(
        'rounded-chip border bg-white px-4 pb-3 pt-2.5 transition-colors duration-150',
        holding ? 'border-brand/50 bg-brand-50/60' : 'border-line',
      )}
    >
      <div className="flex h-6 items-center gap-2">
        <b className="t-item-title truncate font-extrabold">{state.name}</b>
        <span className={cn('t-label font-bold', TONE_TEXT[tone])}>{TREND_LABEL[state.sentiment_trend]}</span>
        {holding && <span className="t-label ml-auto shrink-0 rounded-md bg-brand/10 px-1.5 py-0.5 font-bold text-brand">当前持仓</span>}
      </div>

      <div className="mt-2 flex items-center gap-2">
        <span className="num-mono text-[15px] font-extrabold" style={{ color: TONE_FILL[tone] }}>
          {state.sentiment_score >= 0 ? '+' : ''}
          {state.sentiment_score.toFixed(2)}
        </span>
        <div className="relative h-2 flex-1 rounded-full bg-page">
          <div className="absolute inset-y-0 left-1/2 w-px bg-line" />
          <div
            className="absolute inset-y-0 rounded-full"
            style={{
              backgroundColor: TONE_FILL[tone],
              left: state.sentiment_score >= 0 ? '50%' : `${fillPct}%`,
              width: `${Math.abs(fillPct - 50)}%`,
            }}
          />
        </div>
      </div>

      <div className="t-label mt-1.5 flex justify-between text-ink-500">
        <span>置信度 <b className="num font-bold text-ink-700">{(state.confidence * 100).toFixed(0)}%</b></span>
        <span>样本 <b className="num font-bold text-ink-700">{state.stock_count}</b> 只</span>
      </div>
    </div>
  )
}

function DecisionRow({ data }: { data: SectorRotationPayload }) {
  const d = data.decision
  const llm = d.llm_validation
  const llmTone: Tone = llm?.status === 'agreed' ? 'green' : llm?.status === 'diverged' ? 'orange' : 'blue'

  return (
    <div
      className={cn(
        'mt-4 rounded-chip border px-4 py-3',
        d.should_rotate ? 'border-gold/40 bg-gold-50/70' : 'border-line bg-page',
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <b className={cn('t-item-title font-extrabold', d.should_rotate ? 'text-gold' : 'text-ink-700')}>
          {d.should_rotate ? `建议轮动 → ${d.target_sector ?? '—'}` : '维持当前板块'}
        </b>
        <span className="t-label text-ink-500">
          置信度 <b className="num font-bold text-ink-700">{(d.confidence * 100).toFixed(1)}%</b>
        </span>
        {d.is_fallback && <span className="t-label rounded-md bg-risk/10 px-1.5 py-0.5 font-bold text-risk">防御降级</span>}
        {llm?.status && (
          <span className={cn('t-label font-bold', TONE_TEXT[llmTone])}>
            LLM 复核：{llm.status === 'agreed' ? '同意' : llm.status === 'diverged' ? '分歧（不推翻量化）' : '不可用'}
          </span>
        )}
      </div>
      <p className="t-body mt-1.5 line-clamp-2 leading-[1.6] text-ink-600">{d.llm_rationale || d.reason}</p>
    </div>
  )
}
