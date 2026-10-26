import { useEffect, useState } from 'react'
import { Activity, Cpu, Sparkles, Terminal } from 'lucide-react'

const AGENT_THOUGHTS = [
  {
    tag: 'SCNU-RAG',
    color: 'text-sky-600 bg-sky-50 border-sky-200',
    text: '研报事实抽取中：已锁定佰维存储与美光科技供应链因果链，FOI 100% 坐标溯源通过',
  },
  {
    tag: '对抗投决会',
    color: 'text-indigo-600 bg-indigo-50 border-indigo-200',
    text: 'Bull 多头 vs Bear 空头红队共识达成：存货减值压力释放，贝叶斯 Brier 得分 0.185',
  },
  {
    tag: 'Trend Gate™',
    color: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    text: '战术防御雷达：因果 ZigZag 状态机运行稳健，未触发 C 浪破位一票否决清仓机制',
  },
  {
    tag: 'Fama-MacBeth',
    color: 'text-amber-600 bg-amber-50 border-amber-200',
    text: '因子资产定价：252日截面滚动 OLS 收敛，Newey-West HAC 稳健协方差修正生效',
  },
  {
    tag: 'NALE 拓扑',
    color: 'text-purple-600 bg-purple-50 border-purple-200',
    text: '时空产业链卷积：捕捉半导体存储周期传导时滞，动态 Alpha 阻尼系数 α(t)=0.35',
  },
]

export default function AgentLiveHUD() {
  const [index, setIndex] = useState(0)
  const [visible, setVisible] = useState(true)

  useEffect(() => {
    const timer = setInterval(() => {
      setVisible(false)
      setTimeout(() => {
        setIndex((prev) => (prev + 1) % AGENT_THOUGHTS.length)
        setVisible(true)
      }, 350)
    }, 4200)

    return () => clearInterval(timer)
  }, [])

  const current = AGENT_THOUGHTS[index]

  return (
    <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2.5 rounded-xl border border-slate-200/80 bg-white/80 px-3.5 py-2 shadow-xs backdrop-blur-md transition-all duration-300 hover:border-brand/40 hover:shadow-sm">
      {/* 实时运转心跳指示灯 */}
      <div className="flex items-center gap-2.5">
        <span className="relative flex h-2.5 w-2.5 items-center justify-center">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
        </span>
        <div className="flex items-center gap-1.5 text-[12px] font-bold tracking-tight text-ink-900">
          <Cpu size={13} className="text-brand" />
          <span className="font-mono text-brand">LIVE</span>
          <span>61+ 交易日长跑中</span>
          <span className="hidden text-[11px] font-normal text-ink-400 sm:inline">| 延迟 16ms</span>
        </div>
      </div>

      {/* 智能体实时思维推演流 */}
      <div className="flex flex-1 items-center gap-2 overflow-hidden px-1 sm:max-w-[620px]">
        <Terminal size={12} className="shrink-0 text-ink-400" />
        <div
          className={`flex items-center gap-2 text-[12px] transition-all duration-300 ${
            visible ? 'translate-y-0 opacity-100' : '-translate-y-1 opacity-0'
          }`}
        >
          <span
            className={`shrink-0 rounded-md border px-1.5 py-0.5 text-[10.5px] font-semibold tracking-wide ${current.color}`}
          >
            {current.tag}
          </span>
          <span className="truncate text-ink-700 font-medium">{current.text}</span>
        </div>
      </div>

      {/* 右侧微光指示标 */}
      <div className="hidden items-center gap-1 text-[11px] font-medium text-emerald-700 lg:flex">
        <Sparkles size={11} className="text-emerald-500 animate-pulse" />
        <span>多智能体协同就绪</span>
      </div>
    </div>
  )
}
