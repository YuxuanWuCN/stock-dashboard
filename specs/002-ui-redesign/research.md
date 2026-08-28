# Phase 0 Research: UI 重构与视觉体验升级方案

## 课题 1: 视觉设计系统与 Design Tokens 规范

- **决策**: 采用 CSS 原生自定义属性（`:root` CSS Variables）建立标准化金融主题 Token 系统。
- **理由**: 原生 CSS 变量零运行时开销，天然支持全套样式主题定制，方便全局修改间距、圆角（Border Radius）、卡片阴影（Box Shadow）与专业金融配色（红涨绿跌、亮暗底色）。
- **标准 Tokens 设计**:
  - `--bg-primary`: `#0f172a` (暗调深邃靛蓝) / `#f8fafc` (高对比极简亮色)
  - `--surface-card`: `#1e293b` / `#ffffff`
  - `--stock-up`: `#ef4444` / `#dc2626` (鲜明上涨红)
  - `--stock-down`: `#10b981` / `#059669` (下挫下调绿)
  - `--accent-blue`: `#3b82f6` (品牌高亮蓝)
  - `--radius-lg`: `12px`
  - `--shadow-card`: `0 4px 20px -2px rgba(0, 0, 0, 0.2)`

## 课题 2: 响应式 App-Shell 布局架构

- **决策**: 采用 CSS Grid + Flexbox 构建全局 App-Shell。桌面端为 Sticky 侧边栏模式，移动端为 Drawer 抽屉/Bottom Navigation 模式。
- **理由**: 在 < 768px 断点下，侧边栏通过 CSS `transform: translateX(-100%)` 平滑收起，点击汉堡菜单触发 `:has` 或 `.sidebar-open` 类展开遮罩，解决移动端卡片纵向空间被挤压问题。

## 课题 3: ECharts 响应式与高分屏适配

- **决策**: 使用 `ResizeObserver` API 监听 ECharts 容器元素，配合 `echartsInstance.resize({ animation: { duration: 200 } })`。
- **理由**: 相较于传统 `window.onresize`，`ResizeObserver` 能精准感知 DOM 容器（如侧边栏折叠引发的宽度改变），确保图表无缝重新渲染，消除伸缩滞后。

## 课题 4: 加载反馈与微交互动画

- **决策**: 引入纯 CSS 实现的 `@keyframes skeleton-loading` 骨架屏动画与 Toast 消息提示组件。
- **理由**: 骨架屏相比转圈 Spinner 能够为用户提供确切的布局预期，显著降低心理等待时长。
