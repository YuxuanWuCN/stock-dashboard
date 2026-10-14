import { useCallback, useEffect, useState } from 'react'
import { fetchSectorRotation } from '@/services/api'
import type { SectorRotationPayload, SectorRotationStatus } from '@/types/sectorRotation'

export interface SectorRotationState {
  /** 后端缺数据时为 null —— 本卡片不做 mock 兜底，避免把不存在的决策显示成事实 */
  data: SectorRotationPayload | null
  status: SectorRotationStatus | 'loading'
  ageTradingDays: number | null
  loading: boolean
  error: string | null
  reload: () => void
}

/**
 * 拉取板块轮动每日决策。
 *
 * 与 useHomepage 不同：这里**不准备同构快照**。板块结论一旦伪造就会误导持仓决策，
 * 缺数据时宁可让卡片显示空态与原因。
 */
export function useSectorRotation(): SectorRotationState {
  const [data, setData] = useState<SectorRotationPayload | null>(null)
  const [status, setStatus] = useState<SectorRotationStatus | 'loading'>('loading')
  const [ageTradingDays, setAgeTradingDays] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    fetchSectorRotation()
      .then((resp) => {
        if (cancelled) return
        setData(resp.data)
        setStatus(resp.status)
        setAgeTradingDays(resp.age_trading_days ?? null)
        setError(resp.data ? null : resp.message ?? '暂无板块轮动决策数据')
      })
      .catch((reason: unknown) => {
        if (cancelled) return
        setData(null)
        setStatus('error')
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

  return { data, status, ageTradingDays, loading, error, reload }
}
