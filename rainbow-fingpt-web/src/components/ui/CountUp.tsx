import { useEffect, useState } from 'react'

interface CountUpProps {
  value: string | number
  duration?: number
  className?: string
}

/**
 * 具有数字翻牌/灵性动效的文本渲染组件：
 * 1. 纯数字/带正负号/百分比（如 +122.92%, 3.73, 11.75%）执行平滑缓动渐增 (Cubic Ease-out)；
 * 2. 字母等级（如 AAA）执行毫秒级赛博密码字符解密翻转动效 (Scramble Decode)；
 * 3. 避免硬生生的静态文字，赋予量化系统真实运转的心跳感。
 */
export default function CountUp({ value, duration = 1000, className }: CountUpProps) {
  const [displayValue, setDisplayValue] = useState<string>('')

  useEffect(() => {
    const raw = String(value ?? '').trim()
    if (!raw) {
      setDisplayValue('')
      return
    }

    // 匹配前缀(+/-)、数字主体（含小数、逗号）、后缀(%/x/倍等)
    const match = raw.match(/^([+|-]?)([0-9,.]+)(.*)$/)

    if (!match) {
      // 纯非数字字符（如 AAA / 稳定 / 强），触发短暂赛博字符解码效果
      const chars = '0123456789ABCDEF#$%'
      let frame = 0
      const totalFrames = 10
      const timer = setInterval(() => {
        frame++
        if (frame >= totalFrames) {
          setDisplayValue(raw)
          clearInterval(timer)
        } else {
          const scrambled = raw
            .split('')
            .map(() => chars[Math.floor(Math.random() * chars.length)])
            .join('')
          setDisplayValue(scrambled)
        }
      }, 35)
      return () => clearInterval(timer)
    }

    const [, prefix, numStr, suffix] = match
    const target = parseFloat(numStr.replace(/,/g, ''))
    if (isNaN(target)) {
      setDisplayValue(raw)
      return
    }

    const decimals = (numStr.split('.')[1] || '').length
    const startTime = performance.now()

    let rafId: number
    const update = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(1, elapsed / duration)
      // Ease-out cubic: 1 - (1 - t)^3
      const ease = 1 - Math.pow(1 - progress, 3)
      const current = target * ease
      const formattedNum = decimals > 0 ? current.toFixed(decimals) : Math.round(current).toString()
      setDisplayValue(`${prefix}${formattedNum}${suffix}`)

      if (progress < 1) {
        rafId = requestAnimationFrame(update)
      } else {
        setDisplayValue(raw)
      }
    }

    rafId = requestAnimationFrame(update)
    return () => cancelAnimationFrame(rafId)
  }, [value, duration])

  return <span className={className}>{displayValue || value}</span>
}
