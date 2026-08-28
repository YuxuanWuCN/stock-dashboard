# Tasks: 股票研究看板整体 UI 重新设计与体验提升

**Input**: Design documents from `/specs/002-ui-redesign/`

**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, quickstart.md

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)

---

## Phase 1: Setup (共享基础设置)

- [x] T001 在 `docs/assets/style.css` 中引入并定义原生 CSS Design Tokens (全套金融调色盘、暗黑/高对比主题变量、卡片阴影与圆角)
- [x] T002 [P] 备份并整理 `docs/index.html` 与 `docs/portfolio.html` 原有样式结构

---

## Phase 2: Foundational (核心阻塞先决条件)

- [x] T003 构建响应式 App-Shell 基础结构 (包含 Sticky 侧边栏与 Header 全局状态栏) 在 `docs/index.html`
- [x] T004 [P] 在 `docs/assets/style.css` 中配置 App-Shell Flex/Grid 布局及 @media 响应式断点 (支持 Mobile Drawer)
- [x] T005 [P] 在 `docs/assets/app.js` 中创建全局 Toast 提示组件 API (`window.showToast`)
- [x] T006 [P] 在 `docs/assets/app.js` 中创建 ECharts ResizeObserver 自适应监听封装 (`window.bindChartResize`)

---

## Phase 3: User Story 1 - 现代极简视觉风格与主题升级 (Priority: P1) 🎯 MVP

**Goal**: 建立全套现代金融极简风卡片、高对比排版与层次感强烈的视觉体验。

**Independent Test**: 打开 `index.html` 或 `portfolio.html` 能看到全新高质感卡片、金融红绿涨跌语义高亮及符合 WCAG 2.1 的高对比度排版。

- [x] T007 [P] [US1] 在 `docs/assets/style.css` 中实现通用 Dashboard Card (卡片头部、主体、底部及 Hover 悬浮浮起效果)
- [x] T008 [P] [US1] 在 `docs/assets/style.css` 中重构股票数据表格 (与涨跌幅标签 `.tag-up`, `.tag-down` 精致高亮)
- [x] T009 [US1] 应用 Design Tokens 与 Card 结构至 `docs/index.html` 中的今日关注与单股查询板块
- [x] T010 [US1] 应用 Design Tokens 与 Card 结构至 `docs/portfolio.html` 模拟盘与量化组合页面

---

## Phase 4: User Story 2 - 响应式 App-Shell 布局与导航交互 (Priority: P1)

**Goal**: 实现移动端侧拉抽屉/TabBar与桌面端侧栏协同，SPA 风格无刷新视图切换。

**Independent Test**: 切换屏幕宽度小于 768px 时，侧栏平滑收起为抽屉导航，点击导航平滑切换各视图。

- [x] T011 [P] [US2] 在 `docs/assets/app.js` 中实现侧边栏开闭状态与遮罩层控制逻辑 (`NavState.mobileSidebarOpen`)
- [x] T012 [P] [US2] 在 `docs/assets/app.js` 中实现无刷新视图路由与高亮切换逻辑 (`data-page="today|watchlist|ranking..."`)
- [x] T013 [US2] 整合 `docs/index.html` 移动端汉堡包菜单按钮 (Hamburger Menu) 与 App-Nav 侧拉遮罩

---

## Phase 5: User Story 3 - 看板卡片与 ECharts 交互图表增强 (Priority: P2)

**Goal**: 提升指标卡片信息密度、ECharts 自适应分辨率与富交互悬浮 Tooltip。

**Independent Test**: 拖拽调节窗口时图表 100% 自动 resize；悬浮股票走势节点展现精细收益率与风控指标。

- [x] T014 [P] [US3] 在 `docs/assets/app.js` 中为核心 ECharts 实例 (如模拟盘收益曲线、排行榜热力图) 绑定 `ResizeObserver`
- [x] T015 [P] [US3] 优化 `docs/assets/style.css` 中 ECharts 容器高宽比例与高 DPI 渲染适配
- [x] T016 [US3] 在 `docs/assets/app.js` 中增强 ECharts Tooltip 样式与高亮交互反馈

---

## Phase 6: User Story 4 - 性能与组件状态微交互反馈 (Priority: P3)

**Goal**: 提供 Skeleton 骨架屏占位、加载过渡与 Toast 消息通知。

**Independent Test**: 请求 API 或更新排名时呈现骨架屏闪烁动画，异步操作弹出 Toast 反馈。

- [x] T017 [P] [US4] 在 `docs/assets/style.css` 中定义 `@keyframes skeleton-loading` 骨架屏波浪式淡入淡出动画
- [x] T018 [US4] 在 `docs/assets/app.js` 中为表格与卡片加载过程注入 Skeleton 占位 DOM
- [x] T019 [US4] 在 `docs/assets/app.js` 中绑定 API 操作与 Toast 反馈通知

---

## Phase 7: Polish & Cross-Cutting Concerns (完善与全面测试)

- [x] T020 [P] 运行自动化前端 UI 测试校验契约：`pytest tests/test_frontend_report_ui.py tests/test_frontend_v25.py`
- [x] T021 执行 `quickstart.md` 响应式测试（桌面 1920px、平板 768px、手机 393px）
- [x] T022 清理无用临时 CSS 与调试代码，确认部署完全兼容静态服务器与 API 服务

---

## Dependencies & Execution Order

1. **Setup (Phase 1)** -> **Foundational (Phase 2)**
2. **User Story 1 (P1)** 和 **User Story 2 (P1)** 依赖 Phase 2，可并行推进
3. **User Story 3 (P2)** 依赖 US1 卡片与 ECharts 绑定基础
4. **User Story 4 (P3)** 依赖卡片 DOM 结构完成
5. **Polish (Phase 7)** 依赖全量故事开发完成
