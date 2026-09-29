import { ShieldCheck } from 'lucide-react'
import { Container } from '@/components/layout/PageShell'

/**
 * 07 Footer —— 设计稿被裁断，此为本项目补全的合规版页脚。
 * 金融类页面必须常驻免责声明，字号不低于 12px。
 */
export default function Footer() {
  const links = ['风险揭示', '隐私政策', '用户协议', '联系团队']

  return (
    <footer className="bg-page">
      <Container className="pb-8">
        <div className="flex h-16 flex-col justify-center gap-2 border-t border-line-strong pt-1 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2 text-[15px] font-extrabold text-ink-900">
            <ShieldCheck className="h-[22px] w-[22px] text-brand" strokeWidth={1.9} />
            <span>Rainbow-FinGPT · 银发安心理财助手</span>
          </div>
          <p className="text-[12.5px] text-[#8B95A3] sm:ml-4">
            © 2026 Rainbow-FinGPT 项目组 ｜ 本站数据仅用于学术研究与展示，不构成任何投资建议
          </p>
          <nav className="flex gap-6 text-[13.5px] text-ink-600 sm:ml-auto">
            {links.map((l) => (
              <a key={l} href="#" className="hover:text-ink-900">
                {l}
              </a>
            ))}
          </nav>
        </div>

        <p className="mt-3 rounded-chip border border-dashed border-[#DCE3EB] bg-page px-4 py-3 text-[12px] leading-[1.9] text-ink-400">
          投资有风险，入市需谨慎。历史业绩不代表未来表现，本平台展示的组合与回测结果均为研究性成果，不构成对任何金融产品的推荐或收益承诺。
        </p>
      </Container>
    </footer>
  )
}
