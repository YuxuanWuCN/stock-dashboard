# Tasks: Rainbow-FinGPT 看板前端专业化重构

**输入**: 来自 `specs/018-frontend-professional-upgrade/plan.md` 的计划  
**分支**: `contest-2026`  

## Phase 1: 契约测试基线修复 (Setup)
- [x] T001 恢复缺失的数据合同文档 `项目规划/04-前后端共享数据合同.md`
- [x] T002 验证 5 个前端契约测试文件全部通过（26 passed）

## Phase 2: Design Tokens 与 CSS 架构重构 (Foundational)
- [ ] T003 在 `docs/assets/style.css` 中重构 `:root` 与 `[data-theme="light"]` 双主题 Tokens
- [ ] T004 在 `docs/assets/style.css` 中添加 `.storage-backtest-*` 与 `.monster-*` 语义化组件样式
- [ ] T005 在 `docs/assets/style.css` 中增强金融表格粘性表头、等宽数字（`tabular-nums`）与高密度布局
- [ ] T006 重塑 `docs/assets/style_young.css`，移除紫色渐变覆盖与冲突的 `!important` 声明

## Phase 3: HTML 模板去内联化与 SVG 图标升级 (US1, US2, US3)
- [ ] T007 在 `docs/index.html` Header 中引入专业 SVG Logo 与暗黑/明亮主题切换按钮
- [ ] T008 在 `docs/index.html` 导航栏中使用专业 SVG 微图标替换 Emoji
- [ ] T009 彻底移除 `docs/index.html` 中存储超级周期板块（第 415-463 行）的内联样式
- [ ] T010 彻底移除 `docs/index.html` 中妖股鉴定器板块（第 500-538 行）的内联样式
- [ ] T011 在 `docs/portfolio.html` 中应用相同的专业 SVG 图标与主题类名

## Phase 4: 前端交互脚本增强 (US1, US4)
- [ ] T012 在 `docs/assets/app.js` 中实现主题切换开关监听、本地 `localStorage` 持久化及 ECharts 联动
- [ ] T013 在 `docs/assets/app.js` 中调优 K 线与走势图的暗黑/明亮主题色板
- [ ] T014 在 `docs/assets/portfolio.js` 中接入主题同步与图表高对比配色

## Phase 5: 验证与多端验收 (Verification)
- [ ] T015 运行全量前端 pytest 契约测试，确认 26/26 保持通过
- [ ] T016 运行质量门禁测试与代码规范核验
- [ ] T017 检查多分辨率（移动端 393px、桌面端 1920px）渲染效果
