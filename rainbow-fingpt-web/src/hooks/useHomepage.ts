import { useCallback, useEffect, useState } from 'react'
import { fetchHomepage } from '@/services/api'
import { academicData, allocationData, cashNoteData, equityCurveData, expertData, heroData, riskEvents } from '@/data/mock'
import type { AcademicEconometricsData, HomepageResponse } from '@/types'

export type HomepageSource = 'api' | 'mock'

/**
 * 后端不可用时的兜底快照。
 * 与接口返回同构（真实数据快照），因此离线打开也能完整渲染整页。
 */
const FALLBACK: HomepageResponse = {
  generated_at: '',
  hero: {
    title: heroData.title,
    subtitle: heroData.subtitle,
    metrics: heroData.metrics,
    gauge: heroData.gauge,
  },
  equityCurve: equityCurveData,
  allocation: allocationData,
  cashNote: cashNoteData,
  riskEvents,
  expert: expertData,
  academic: academicData,
}

/**
 * 接口返回可能缺块（后端降级、字段新增），因此按 Partial 接收。
 * 逐块兜底：少哪一块就用快照补哪一块，避免整页空白。
 */
type PartialHomepage = Partial<Omit<HomepageResponse, 'hero' | 'expert'>> & {
  hero?: Partial<HomepageResponse['hero']>
  expert?: Partial<HomepageResponse['expert']>
}

function withFallback(raw: PartialHomepage): HomepageResponse {
  return {
    generated_at: raw.generated_at ?? '',
    hero: { ...FALLBACK.hero, ...(raw.hero ?? {}) },
    equityCurve: raw.equityCurve?.dates?.length ? (raw.equityCurve as HomepageResponse['equityCurve']) : FALLBACK.equityCurve,
    allocation: raw.allocation?.length ? (raw.allocation as HomepageResponse['allocation']) : FALLBACK.allocation,
    cashNote: raw.cashNote ?? FALLBACK.cashNote,
    riskEvents: raw.riskEvents?.length ? (raw.riskEvents as HomepageResponse['riskEvents']) : FALLBACK.riskEvents,
    expert: {
      ...FALLBACK.expert,
      ...(raw.expert ?? {}),
      correlation: raw.expert?.correlation ?? FALLBACK.expert.correlation,
    },
    academic: raw.academic ?? FALLBACK.academic,
    meta: raw.meta,
  }
}

export interface HomepageState {
  data: HomepageResponse
  /** 数据来源：api = 实时接口，mock = 快照兜底 */
  source: HomepageSource
  loading: boolean
  /** 回退到快照时的原因，便于排查（接口正常时为 null） */
  error: string | null
  reload: () => void
}

/**
 * 拉取首页视图模型。
 * 接口失败不抛错——直接回退到同构快照，保证页面永远可渲染。
 */
export function useHomepage(): HomepageState {
  const [data, setData] = useState<HomepageResponse>(FALLBACK)
  const [source, setSource] = useState<HomepageSource>('mock')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    fetchHomepage()
      .then((payload) => {
        if (cancelled) return
        setData(withFallback(payload))
        setSource('api')
        setError(null)
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        // 后端不可用是预期内的情况（纯静态托管），用快照继续渲染
        setData(FALLBACK)
        setSource('mock')
        setError(reason instanceof Error ? reason.message : '接口不可用')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [nonce])

  const reload = useCallback(() => setNonce((value) => value + 1), [])

  return { data, source, loading, error, reload }
}
