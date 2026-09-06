# Phase 0 Research: 金融投研看板专业化与 Anti-Slop 设计规范研究

## 课题 1: 视觉风格定位（Anti-Slop & Anti-Default）

- **决策**: 放弃以“AI紫”（`#6366f1` / `#8b5cf6`）为代表的通用大模型套壳 UI 风格，转向**现代金融工程量化终端风格（Institutional Quant Terminal）**。
- **依据与准则**:
  - `/design-taste-frontend` 准则 4.2 明确禁止默认滥用紫色发光与霓虹渐变。
  - 金融工具的核心诉求在于**数据的严谨性、清晰度与权威感**。
  - 核心基色采用石板灰（Slate/Zinc）体系，主强调色采用经过调校的金融高对比蓝（Sapphire Blue `#2563eb`），搭配 A 股经典的红色（上涨/多头 `#ef4444`）与翡翠绿（下跌/空头 `#10b981`）。

## 课题 2: 图标系统由 Emoji 到矢量 SVG 微图标

- **决策**: 移除在导航栏、标题、按钮中充斥的各种操作系统 Emoji，统一采用 1.5px 线宽的内联 SVG 微图标。
- **依据与准则**:
  - `/design-taste-frontend` 准则 3.D 明确规范：默认禁止在代码与界面展示中随意散落表情符号，应使用严谨的图标库图元替代。
  - Emoji 在 Windows 11（彩色平面）、macOS/iOS（拟真立体）、Android（各厂商定制）上显示效果割裂，且在暗黑背景下经常出现不可控的亮色底边，造成强烈的视觉噪点。
  - SVG 图标具备矢量无损、随字体颜色继承（`currentColor`）、与暗黑/亮色主题完美响应的优势。

## 课题 3: 消除内联样式（Inline Styles）与样式架构整合

- **决策**: 将 `docs/index.html` 中分散在存储超级周期模块、妖股鉴定器、出版级图表容器等处的数十处 `style="..."` 全部迁移至语义化的 CSS 类，并整合 `style.css` 与 `style_young.css`。
- **依据与准则**:
  - 硬编码内联样式具有最高特异性（Specificity），极难通过媒体查询（`@media`）或主题属性选择器（`[data-theme="..."]`）进行样式覆盖，是导致移动端错位与暗黑模式适配失败的元凶。
  - 整合后形成“Tokens 变量层 -> Base 基础排版 -> Components 组件库 -> Layout 布局与响应式 -> Pro/Young 微动效增强层”的清晰单向流。

## 课题 4: 金融数据等宽排版（Tabular Figures）

- **决策**: 全局关键数值采用 `font-family: var(--font-mono); font-variant-numeric: tabular-nums;`。
- **依据与准则**:
  - 比例字体（Proportional Font）中数字 `1` 和 `8` 宽度不一致，导致价格列表、百分比收益率和排行榜纵向扫视时数字抖动、无法对齐。
  - 等宽数字使每一位数字占据相同字宽，极大提升高频行情对比和回测指标核验时的视觉效率。
