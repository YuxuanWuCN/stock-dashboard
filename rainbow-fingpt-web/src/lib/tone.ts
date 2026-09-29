import type { Tone } from '@/types'

/** 文本/描边色：用于标题、数值 */
export const TONE_TEXT: Record<Tone, string> = {
  green: 'text-brand',
  red: 'text-risk',
  blue: 'text-tech',
  gold: 'text-gold',
  orange: 'text-[#D9722A]',
}

/** 实心图标填充色 */
export const TONE_FILL: Record<Tone, string> = {
  green: '#26A17F',
  red: '#F4696C',
  blue: '#3D87E8',
  gold: '#F08634',
  orange: '#F08634',
}

/** 浅底：hover 或强调背景 */
export const TONE_SOFT: Record<Tone, string> = {
  green: 'bg-brand-50',
  red: 'bg-risk-50',
  blue: 'bg-tech-50',
  gold: 'bg-gold-50',
  orange: 'bg-gold-50',
}

/** 卡片 hover 态：描边 + 浅底都跟着语义色走 */
export const TONE_CARD_HOVER: Record<Tone, string> = {
  green: 'enabled:hover:border-brand/40 enabled:hover:bg-brand-50/70',
  red: 'enabled:hover:border-risk/40 enabled:hover:bg-risk-50/70',
  blue: 'enabled:hover:border-tech/40 enabled:hover:bg-tech-50/70',
  gold: 'enabled:hover:border-gold/40 enabled:hover:bg-gold-50/70',
  orange: 'enabled:hover:border-[#F08634]/40 enabled:hover:bg-gold-50/70',
}
