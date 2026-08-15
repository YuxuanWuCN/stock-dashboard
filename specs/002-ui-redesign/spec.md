# Feature Specification: 股票研究看板整体 UI 重新设计与体验提升

**Feature Branch**: `002-ui-redesign`

**Created**: 2026-08-14

**Status**: Draft

**Input**: 股票研究看板 2.5 整体 UI 视觉提升、响应式布局优化、图表数据展示增强与动画体验优化

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 现代极简视觉风格与主题调色盘升级 (Priority: P1)

作为股票分析看板的用户，我希望界面采用现代化、专业且高品质的金融视觉设计语言（支持暗色/亮色精致质感，清晰的层次结构与高对比度字体），以便长期盯着行情和数据时视觉体验舒适、信息焦点明确。

**Why this priority**: 视觉第一印象直接决定用户对量化分析工具的专业度感知，建立规范的 CSS 变量系统与现代调色盘是所有 UI 组件重构的基础。

**Independent Test**: 用户在浏览器打开 `index.html` 或 `portfolio.html` 时，可以看到全新的现代卡片风格、高质感调色盘、渐变阴影与符合金融应用的高对比度排版。

**Acceptance Scenarios**:

1. **Given** 初始页面加载，**When** 用户查看看板，**Then** 主体界面呈现现代金融极简设计风格，包含层级分明的阴影、精致圆角与清晰的色彩语义（上涨红/绿/黄提示分明）。
2. **Given** 页面包含各种卡片、图表和表格，**When** 视口尺寸变化或处于不同分辨率下，**Then** 背景与文本间保持符合 WCAG 2.1 AA 标准的高对比度阅读体验。

---

### User Story 2 - 响应式 App-Shell 布局与流畅导航交互 (Priority: P1)

作为移动端或不同屏幕尺寸的用户，我希望系统提供响应式的全局 App-Shell 架构（支持顶部导航栏、侧边栏收起/展开、手势/点击无缝切换模块），以便在手机、平板或台式机上都能高效浏览自选股、排行榜和模拟盘。

**Why this priority**: 目前移动端或窄屏视角下导航和卡片排列容易挤压，响应式布局与无缝导航切换是多端体验的核心。

**Independent Test**: 在窗口缩放至移动端宽度（如 < 768px）时，侧边栏能够自动收起并转换为遮罩/抽屉式导航，点击导航项能够无缝平滑切换页面视图且不产生页面重载刷屏。

**Acceptance Scenarios**:

1. **Given** 用户使用手机或窄屏幕打开应用，**When** 切换不同功能模块（今日关注、自选股、排行榜、单股查询等），**Then** 导航菜单以侧拉抽屉或响应式 TabBar 形式展现，不占用核心图表阅读区域。
2. **Given** 用户点击顶部或侧栏导航按钮，**When** 切换视图，**Then** 当前激活项高亮，对应内容区域以微平滑过渡动画加载，URL 状态或 hash 保持同步。

---

### User Story 3 - 看板卡片与 ECharts 交互式图表展示增强 (Priority: P2)

作为关注量化指标与历史收益的投资者，我希望核心看板卡片（如胜率、风险收益比、调仓建议）和 ECharts 走势图表具备更高的信息密度、自适应高 DPI 缩放以及更加直观的悬浮提示（Tooltip）与数据联动，以便快速捕捉关键交易信号。

**Why this priority**: 图表和数据卡片是股票分析的核心载体，图表交互与卡片排版直接决定数据解读的效率。

**Independent Test**: 调整浏览器窗口大小时，ECharts 图表能够无缝自动 resize；悬浮查看数据点时呈现格式化后的收益率与风险区间，高亮当前关注焦点。

**Acceptance Scenarios**:

1. **Given** 包含 ECharts 走势图或热力图的页面，**When** 调整窗口大小，**Then** 图表实时自适应重新绘制，不产生变形、溢出或横向滚动条。
2. **Given** 用户浏览多维度股票风险/收益排行榜，**When** 悬浮或点击卡片，**Then** 提示框展示精细化的指标解释（如最大回撤、夏普比率、建议仓位），且卡片有微弹簧缩放反馈。

---

### User Story 4 - 性能与组件状态微交互反馈 (Priority: P3)

作为在网络波动或数据加载期间使用的用户，我希望页面数据加载时有极具现代感的 Skeleton骨架屏 与 状态过渡微动画，并在刷新数据或切换个股时提供毫秒级平滑过渡，以便感知系统运行状态并获得顺畅的交互体验。

**Why this priority**: 良好的加载反馈与骨架屏能显著降低用户感知延迟，提升整体应用的拟物感与现代全栈应用质感。

**Independent Test**: 在请求数据接口或加载本地数据时，卡片区展示骨架屏占位，加载完成后平滑淡入呈现真正内容。

**Acceptance Scenarios**:

1. **Given** 页面发起 API 数据获取或后台排序构建，**When** 处于数据等待状态，**Then** 相应的卡片与表格区域呈现 CSS Skeleton 闪烁动画而非空白或错位。
2. **Given** 数据加载成功或失败，**When** 状态更新，**Then** 弹出微提示 Toast 或状态栏指示器，明确告知更新时间与数据最新状态。

---

### Edge Cases

- **极窄屏幕（< 360px）**：图表与复杂表格自动转为单列垂直堆叠布局，隐藏非核心次要字段。
- **高分屏与 Retina 视网膜屏（2K/4K）**：ECharts 及 Font-Awesome/SVG 图标能够按照高 DPI 渲染，无糊边。
- **网络中断或 API 加载失败**：优雅降级显示无网络/数据获取失败图标与一键重试按钮，提示用户查看本地缓存数据。
- **大量数据列表展示（> 100 只股票）**：表格/卡片列表支持分页或虚拟列表，避免 DOM 过多导致页面卡顿。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统必须建立统一的 CSS Design Tokens 变量体系（包含背景色、表面色、主色调、涨跌语义色、字号阶梯、阴影深度与圆角规格）。
- **FR-002**: 系统必须实现响应式的 App-Shell 布局结构，支持 Desktop 侧边栏模式与 Mobile 抽屉导航模式的自适应无缝切换。
- **FR-003**: 导航系统必须支持 SPA 风格的视图无刷新切换，并保持顶部全局状态栏（数据版本、数据刷新时间、服务器连通状态）实时可见。
- **FR-004**: 所有 ECharts 实例必须绑定 ResizeObserver 监听，确保窗口变动或侧边栏展开/收起时 100% 自适应容器尺寸。
- **FR-005**: 核心看板卡片（今日关注、风险收益排行榜、模拟盘收益）必须采用模块化 Card 组件设计，并具备 Hover 上浮、高亮与交互反馈。
- **FR-006**: 数据加载与无数据状态必须分别提供统一的 Skeleton 骨架屏组件与 Empty State 空白提示组件。
- **FR-007**: 系统必须在全局提供 Toast 消息提示组件，用于异步操作（如一键调仓、数据刷新、自选添加）的实时反馈。
- **FR-008**: 股票数据表格在移动端必须支持横向平滑滚动或自适应卡片化转换，保证关键列（股票代码、名称、现价、涨跌幅、短线评分）优先显示。
- **FR-009**: 系统 UI 必须兼容 Chrome, Edge, Safari 及移动端主流浏览器，无特定浏览器专属 Hack。
- **FR-010**: 系统必须保留原有 2.5 版所有业务功能逻辑（无损重构），并支持无缝关联 `portfolio.html` 和 `index.html`。

### Key Entities

- **ThemeToken**: 定义 UI 的全局颜色（Primary, Secondary, Up-Red, Down-Green, Surface-Card, Border-Subtle）、间距（Padding/Margin）、字号与阴影。
- **NavState**: 管理当前激活页面视图（today, watchlist, ranking, query, detail, paper）以及移动端侧边栏开闭状态（sidebarOpen: boolean）。
- **DashboardCard**: 表现层卡片组件模型，包含 Header、Body、Footer 区域以及 Status (loading/success/error) 属性。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 页面首次可交互时间（TTI）控制在 1.5 秒以内，首屏绘制视觉无明显闪烁现象。
- **SC-002**: 移动端（宽度 375px - 430px）和桌面端（宽度 1280px - 1920px）下无横向非预期溢出滚动条，100% 界面布局响应式对齐。
- **SC-003**: 界面色彩对比度符合 WCAG 2.1 AA 级标准（主文本与背景对比度 >= 4.5:1）。
- **SC-004**: 窗口尺寸调整时，图表自适应重绘无延缓，Resize 响应耗时 <= 100ms。
- **SC-005**: 用户在各个功能页面（今日关注、自选股、排行榜、模拟盘）间切换延迟 <= 50ms。

## Assumptions

- 前端开发基于原生 HTML5 + Vanilla CSS3 + Modern JavaScript (ES6+)，并沿用现有的 ECharts CDN 依赖。
- 不引入重型前端框架（如 React/Vue 全家桶打包），确保现有部署结构（Render / GitHub Pages / 静态托管）保持 100% 兼容。
- 原有的后端 API / 数据接口格式与 JSON 结构保持兼容，UI 升级仅聚焦于视觉呈现与交互组件层。
