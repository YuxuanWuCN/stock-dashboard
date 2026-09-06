# 实现计划：Rainbow-FinGPT 看板前端专业化重构与现代金融设计规范升级

**分支**：`contest-2026` | **日期**：2026-09-06 | **规格**：[specs/018-frontend-professional-upgrade/spec.md](spec.md)  
**输入**：来自 `specs/018-frontend-professional-upgrade/spec.md` 的功能规格与 `/design-taste-frontend` 规范

## 1. 概要 (Summary)

重构 Rainbow-FinGPT 股票投研看板的前端设计系统。彻底根除 AI 模板紫色渐变与大面积光晕，用统一精致的 1.5px SVG 微图标替换全部操作系统 Emoji，消除所有硬编码内联样式，统一建立支持 Dark/Light 双主题的 Design Tokens 体系，并全面引入等宽金融数字与紧凑表格布局，同时保证 100% 满足现有 pytest 契约测试。

---

## 2. 技术背景 (Technical Context)

- **语言/环境**: 原生 HTML5, CSS3, ES6+ JavaScript, Python 3.13 (pytest 自动化测试)
- **可视化库**: ECharts 5.5.1 (通过 fastly.jsdelivr.net CDN 引入，带 bootcdn 兜底)
- **目标平台**: 现代主流浏览器 (Chrome, Edge, Safari, Firefox)，自适应桌面端与移动端 (393px - 1920px)
- **性能指标**: 页面完全脱离大型打包工具（Webpack/Vite 构建），零编译等待，即改即显；ECharts 实例绑定 `ResizeObserver` 毫秒级自适应

---

## 3. 宪章检查与门禁 (Constitution Check)

- **代码与测试可复现**: 测试必须覆盖所有契约，所有 26 个 pytest 契约测试必须 100% PASSED。
- **不破坏数据契约**: 所有 DOM ID、历史分析报告结构与策略文件路径保持绝对向后兼容。
- **免责合规**: 保持“研究参考，不构成买卖建议”等必要合规警示。

---

## 4. 实施阶段与架构安排

### 阶段 1: 样式架构重构与 Design Tokens 建立
- 在 `docs/assets/style.css` 中建立系统化的 `:root`（默认 Dark 模式）与 `[data-theme="light"]`（清爽 Light 模式）Design Tokens。
- 提取并规范存储超级周期模块与妖股鉴定器的专属 CSS 规则，彻底消灭 `index.html` 中的内联样式。
- 调整 `docs/assets/style_young.css`，移除破坏性的紫光覆盖，保留平滑交互与现代感微过渡。

### 阶段 2: HTML 结构精细化与矢量 SVG 图标植入
- 重构 `docs/index.html`：
  - Header：注入专业 SVG 标识，添加主题切换按钮。
  - Nav：将 7 个导航切换按钮的 Emoji 替换为内嵌 SVG 图标。
  - Paper 页面：将 `storage-backtest-card` 转换为语义类名，移除内联 style。
  - Monster 页面：将 `monster-stats-grid` 等处的硬编码内联 style 转换为语义类名。
- 重构 `docs/portfolio.html`：同步更新样式引入与导航图标。

### 阶段 3: 前端交互脚本增强（主题切换与图表联动）
- 在 `docs/assets/app.js` 中增加全局主题初始化、持久化与切换事件。
- 在主题切换时，动态更新 K 线图、大盘对比图、净值走势图的背景色与网格线色。
- 在 `docs/assets/portfolio.js` 中同步主题联动与图表色彩渲染。

### 阶段 4: 全量测试与质量门禁验收
- 执行 `python -m pytest tests/test_frontend_*.py -v`。
- 执行本地浏览器多分辨率自适应核验。
