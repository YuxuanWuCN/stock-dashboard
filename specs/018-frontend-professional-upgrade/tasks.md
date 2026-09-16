# Tasks: Rainbow-FinGPT 看板前端专业化重构

**输入**: 来自 `specs/018-frontend-professional-upgrade/plan.md` 的计划  
**分支**: `contest-2026`  
**最近更新**: 2026-09-15

**勾选口径**：`[x]` 表示该项在当前工作树中已达成。标注「本次」的条目由 2026-09-15 会话完成，其余为先前进行中的工作已完成；本次未改动的部分已在条目内注明。

## Phase 1: 契约测试基线修复 (Setup)
- [x] T001 恢复缺失的数据合同文档 `项目规划/04-前后端共享数据合同.md`
- [x] T002 验证前端契约测试文件全部通过（基线 26 passed）

## Phase 2: Design Tokens 与 CSS 架构重构 (Foundational)
- [x] T003 在 `docs/assets/style.css` 中重构 `:root` 与 `[data-theme="light"]` 双主题 Tokens
- [x] T004 在 `docs/assets/style.css` 中添加 `.storage-backtest-*` 与 `.monster-*` 语义化组件样式
- [x] T005 在 `docs/assets/style.css` 中增强金融表格粘性表头、等宽数字（`tabular-nums`）与高密度布局
      ↳ **本次补齐粘性表头**：原注释声称"粘性表头优化"但全文件无 `thead th { position: sticky }`；同时为滚动容器补 `overflow-y: auto` + `max-height`（仅有 `overflow-x: auto` 时粘性表头不会生效）
- [x] T006 重塑 `docs/assets/style_young.css`，移除紫色渐变覆盖与冲突的 `!important` 声明

## Phase 3: HTML 模板去内联化与 SVG 图标升级 (US1, US2, US3)
- [x] T007 在 `docs/index.html` Header 中引入专业 SVG Logo 与暗黑/明亮主题切换按钮
      ↳ **本次补 `aria-pressed`**，并修复 JS 查询 `.theme-text` 与标记 `class="theme-toggle-text"` 不一致导致按钮文案永不更新的缺陷
- [x] T008 在 `docs/index.html` 导航栏中使用专业 SVG 微图标替换 Emoji
- [ ] T009 彻底移除 `docs/index.html` 中存储超级周期板块的内联样式
      ↳ **未完成**：`docs/index.html` 仍有 11 处 `style="..."`。属 US3 范围，本轮检查表已明确排除
- [ ] T010 彻底移除 `docs/index.html` 中妖股鉴定器板块的内联样式
      ↳ **未完成**：同 T009
- [x] T011 在 `docs/portfolio.html` 中应用相同的专业 SVG 图标与主题类名
      ↳ **本次补齐**：`aria-pressed`、首屏主题引导脚本、缓存版本串

## Phase 4: 前端交互脚本增强 (US1, US4)
- [x] T012 在 `docs/assets/app.js` 中实现主题切换开关监听、本地 `localStorage` 持久化及 ECharts 联动
      ↳ **本次加固**：读写各自 try/catch 兜底（存储禁用不再中断 `DOMContentLoaded`）；图表实例登记表 `themedChartInstances()` 跳过未创建/已销毁实例；移除永不成立的 `state.paperCurveChart` 死引用
- [x] T013 在 `docs/assets/app.js` 中调优 K 线与走势图的暗黑/明亮主题色板
      ↳ **本次补齐**：模拟盘净值曲线为内联 SVG，原来硬编码 `#e5e7eb`/`#6b7280`；改为 `.paper-curve-grid` / `.paper-curve-label` 由 CSS Token 驱动，切主题无需重绘
- [x] T014 在 `docs/assets/portfolio.js` 中接入主题同步与图表高对比配色
      ↳ **本次加固**：存储兜底、`aria-pressed`、`.theme-toggle-text` 选择器对齐

## Phase 5: 验证与多端验收 (Verification)
- [x] T015 运行全量前端 pytest 契约测试
      ↳ **本次结果**：6 个文件 / **50 passed**（基线 26 + 本次新增 24）
- [x] T016 运行质量门禁测试与代码规范核验
      ↳ **small ✅ 通过、medium ✅ 通过**；**heavy ❌ 14 failed / 793 passed**，失败项全部为 `src/` 后端与未提交的其它 spec 进行中测试（`test_calibration_stability`、`test_download_csmar_carhart_factors`、`test_green_backtest_runner`、`test_storage_gold_joint_runner`、`test_validate_teacher_framework` 等），已自动登记为 BUG-0003 / BUG-0004，与本次前端改动无交集
- [ ] T017 检查多分辨率（移动端 393px、桌面端 1920px）渲染效果
      ↳ **部分完成**：`style.css` 已补 393px / 1440px / 1920px 权威断点与宽屏内容宽度收敛；**真实浏览器渲染核验未完成**（本机未安装 Chrome，`agent-browser` 无法启动），已改为 Node 侧独立逻辑验证（9 项，含存储抛错路径）

## 本次会话新增产物

- `tests/test_frontend_theme_contract.py`：24 项静态契约测试（双主题 / 金融数字 / 响应式），已通过 7 项突变验证确认非空洞
- `specs/018-frontend-professional-upgrade/spec.md` §4：补写 FR-005~FR-011 实现期补充要求
- `specs/018-frontend-professional-upgrade/checklists/frontend.md`：40 项要求质量检查表，当前 18 项已闭合
