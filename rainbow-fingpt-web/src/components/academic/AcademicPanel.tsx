import { cn } from '@/lib/cn'
import type { AcademicEconometricsData } from '@/types'

/**
 * 学术因子与计量定价面板
 * 四大模块：Fama-MacBeth 回归 / Rank IC / NALE 拓扑矩阵 / BibTeX 引用
 * 注入 ExpertModeSection 的第二个 Tab。
 */
export default function AcademicPanel({ data }: { data: AcademicEconometricsData }) {
  return (
    <div className="divide-y divide-line">
      {/* 模块 1: Fama-MacBeth */}
      <AcademicSection title="1. Fama-MacBeth 滚动两阶段回归与因式定价" desc="双阶段 OLS 截面风险溢价估计与 Newey-West HAC 异方差自相关稳健标准误检验">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="text-left text-[11px] font-semibold text-ink-400">
              <th className="pb-1.5 pr-2">因式名称</th>
              <th className="pb-1.5 pr-2 text-right">Beta (β)</th>
              <th className="pb-1.5 pr-2 text-right">t-Stat</th>
              <th className="pb-1.5 pr-2 text-right">p-Value</th>
              <th className="pb-1.5">经济学含义</th>
            </tr>
          </thead>
          <tbody>
            {data.famaMacBeth.map((f) => (
              <tr key={f.name} className="border-t border-[#F2F5F9] transition-colors hover:bg-page">
                <td className="py-1.5 pr-2 text-ink-700">{f.name}</td>
                <td className="num-mono py-1.5 pr-2 text-right font-bold text-brand">{f.beta.toFixed(2)}</td>
                <td className="num-mono py-1.5 pr-2 text-right text-ink-700">{f.tStat.toFixed(2)}</td>
                <td className="num-mono py-1.5 pr-2 text-right text-ink-700">{f.pValue}</td>
                <td className="py-1.5 text-ink-600">{f.interpretation}</td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* CSMAR 映射子表 */}
        <h5 className="mt-3 mb-1.5 text-[12px] font-bold text-ink-800">CSMAR 原生数据源与学术字段映射表</h5>
        <table className="w-full border-collapse text-[12px]">
          <thead>
            <tr className="text-left text-[11px] font-semibold text-ink-400">
              <th className="pb-1.5 pr-2">因式变量</th>
              <th className="pb-1.5 pr-2">开源免费源</th>
              <th className="pb-1.5 pr-2">Wind 商业字段</th>
              <th className="pb-1.5">国泰安 (CSMAR) 字段</th>
            </tr>
          </thead>
          <tbody>
            {data.csmarMapping.map((m) => (
              <tr key={m.variable} className="border-t border-[#F2F5F9] transition-colors hover:bg-page">
                <td className="py-1 pr-2 text-ink-700">{m.variable}</td>
                <td className="py-1 pr-2 text-ink-600">{m.openSource}</td>
                <td className="num-mono py-1 pr-2 text-ink-500">{m.windField}</td>
                <td className="num-mono py-1 text-ink-500">{m.csmarField}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </AcademicSection>

      {/* 模块 2: Rank IC */}
      <AcademicSection title="2. Soft-Spearman Rank IC 跨周期收敛指标" desc="基于 156 支标的、34 期截面测试">
        <table className="w-full border-collapse text-[12.5px]">
          <thead>
            <tr className="text-left text-[11px] font-semibold text-ink-400">
              <th className="pb-1.5 pr-2">预测周期</th>
              <th className="pb-1.5 pr-2 text-right">Static IC</th>
              <th className="pb-1.5 pr-2 text-right">Temporal IC</th>
              <th className="pb-1.5 pr-2 text-right">IC-IR</th>
              <th className="pb-1.5 pr-2 text-right">Harvey-Liu t</th>
              <th className="pb-1.5 text-right">精度提升</th>
            </tr>
          </thead>
          <tbody>
            {data.rankIc.map((r) => (
              <tr
                key={r.horizon}
                className={cn(
                  'border-t border-[#F2F5F9] transition-colors hover:bg-page',
                  r.isHighlight && 'bg-[rgba(16,185,129,0.06)]',
                )}
              >
                <td className={cn('py-1.5 pr-2 text-ink-700', r.isHighlight && 'font-bold')}>{r.horizon}</td>
                <td className="num-mono py-1.5 pr-2 text-right text-ink-700">{r.staticIc.toFixed(4)}</td>
                <td className={cn('num-mono py-1.5 pr-2 text-right', r.isHighlight ? 'font-bold text-brand' : 'text-ink-700')}>{r.temporalIc.toFixed(4)}</td>
                <td className={cn('num-mono py-1.5 pr-2 text-right', r.isHighlight ? 'font-bold text-brand' : 'text-ink-700')}>{r.icIr.toFixed(3)}</td>
                <td className="num-mono py-1.5 pr-2 text-right text-ink-700">{r.harveyLiuT.toFixed(2)}</td>
                <td className={cn('num-mono py-1.5 text-right', r.isHighlight ? 'font-bold text-brand' : 'text-ink-700')}>{r.improvement}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-2 space-y-0.5 rounded-lg bg-page px-3 py-2 text-[11.5px] leading-relaxed text-ink-600">
          <p>• <strong>{data.notes.spilloverCapture}</strong></p>
          <p>• <strong>{data.notes.factorHalfLife}</strong></p>
        </div>
      </AcademicSection>

      {/* 模块 3: NALE 拓扑 */}
      <AcademicSection title="3. NALE v2 非对称经济邻接拓扑矩阵" desc="有向非对称传导：行→接收方，列→冲击溢出方">
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[12px]">
            <thead>
              <tr className="text-[11px] font-semibold text-ink-400">
                <th className="pb-1.5 pr-2 text-left">接收 \ 溢出</th>
                {data.naleTopology.labels.map((l) => (
                  <th key={l} className="whitespace-nowrap px-1 pb-1.5 text-center">{l}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.naleTopology.matrix.map((row, ri) => (
                <tr key={data.naleTopology.labels[ri]} className="border-t border-[#F2F5F9]">
                  <td className="whitespace-nowrap py-1 pr-2 font-semibold text-ink-700">{data.naleTopology.labels[ri]}</td>
                  {row.map((val, ci) => {
                    const intensity = Math.abs(val)
                    const bg = ri === ci
                      ? 'bg-ink-800 text-white'
                      : intensity >= 0.5 ? 'bg-brand/20 text-brand font-bold'
                      : intensity >= 0.3 ? 'bg-brand/10 text-ink-800'
                      : val < 0 ? 'bg-risk/10 text-risk'
                      : 'text-ink-500'
                    return (
                      <td key={ci} className={cn('num-mono px-1 py-1 text-center text-[11.5px]', bg)}>
                        {val.toFixed(2)}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="mt-2 space-y-0.5 rounded-lg bg-page px-3 py-2 text-[11.5px] leading-relaxed text-ink-600">
          <p>• {data.notes.placeboTest}</p>
          <p>• {data.notes.trendGate}</p>
        </div>
      </AcademicSection>

      {/* 模块 4: BibTeX */}
      <AcademicSection title="4. 学术研报文献与 BibTeX 引用" desc={`源自论文《${data.citation.paperTitle}》`}>
        {data.citation.paperUrl && (
          <a
            href={data.citation.paperUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="mb-2 inline-block rounded-md bg-[#EFF6FF] px-2 py-1 text-[12px] font-medium text-[#3D87E8] transition-colors hover:bg-[#DBEAFE]"
          >
            阅读学术论文完整 HTML 研报 ↗
          </a>
        )}
        <pre className="overflow-x-auto rounded-lg bg-ink-800 px-4 py-3 text-[11.5px] leading-relaxed text-[#C6D2E0]">
          {data.citation.bibtex}
        </pre>
      </AcademicSection>
    </div>
  )
}

function AcademicSection({
  title,
  desc,
  children,
}: {
  title: string
  desc: string
  children: React.ReactNode
}) {
  return (
    <section className="px-[22px] py-3">
      <h4 className="mb-0.5 text-[13px] font-extrabold text-ink-900">{title}</h4>
      <p className="mb-2 text-[11.5px] text-ink-500">{desc}</p>
      {children}
    </section>
  )
}
