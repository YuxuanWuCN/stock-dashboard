# 功能规格：Rainbow-FinGPT 看板前端专业化重构与现代金融设计规范升级

**功能编号**：018-frontend-professional-upgrade  
**创建日期**：2026-09-06  
**状态**：进行中  
**优先级**：P1  

## 1. 概述 (Overview)

针对《Rainbow-FinGPT 股票智能量化投研看板》前端进行全方位专业化重构。结合 `/design-taste-frontend`（反平庸专业前端品味规范）与 `/speckit-plan-zh`（规范驱动工程规划），将当前带有“AI紫渐变”、“杂乱Emoji”、“内联CSS散落”、“黑白主题冲突”的初期页面，升级为符合中国国际大学生创新大赛（国创）评审标准与专业量化机构（如 Bloomberg / TradingView / Linear 级）水准的**现代专业金融量化投研终端**。

---

## 2. 用户场景与故事 (User Scenarios & Stories)

### User Story 1 - 专业金融设计语言与统一双主题体系 (Priority: P1)
作为创新大赛评审专家或机构量化研究员，我希望投研看板呈现权威、严谨、现代的金融终端设计质感（支持专业暗黑量化终端与极简清爽明色白盘无缝切换，消除刺眼的 AI 霓虹紫渐变与塑料感光晕），以便在高信息密度下专注于量化因子、定价估值与风控指标的深度解读。

- **验收标准**：
  1. 全站采用标准化的 Design Tokens（`[data-theme="dark"]` 与 `[data-theme="light"]`）。
  2. 彻底移除所有 `#6366f1` / `#8b5cf6` 紫色大渐变与高发光阴影，改用精准的金融蓝（Sapphire `#2563eb`）与石板灰体系（Slate `#090d16` / `#111827` / `#1e293b`）。
  3. 点击右上角主题切换按钮，全站（含所有卡片、背景、边框、ECharts 坐标轴网格线）在 0.2s 内平滑切换且无局部颜色残留。

### User Story 2 - 全局 Emoji 替换与精细 SVG 微图标系统 (Priority: P1)
作为严肃金融工具的使用者，我希望导航栏、板块标题、状态标签和操作按钮使用统一风格（1.5px 线宽）的专业 SVG 微图标替代平台各异且显得业余的系统 Emoji 表情包，提升整个系统的学术感与商业成熟度。

- **验收标准**：
  1. 顶部 Header、7 大页面切换导航按钮、各板块标题栏、自选股/排行榜/模拟盘按钮中的 Emoji 全部替换为统一风格的内联矢量 SVG 图标或精致文字徽章。
  2. 图标在不同屏幕（Retina 高分屏与标准屏）及不同系统（Windows/macOS/iOS/Android）下均表现锐利、粗细一致。

### User Story 3 - 代码工程化：消除内联样式与 CSS 架构融合 (Priority: P1)
作为代码维护者与跨端用户，我希望前端 HTML 中的硬编码内联样式（Inline Styles）全部抽象为语义化的 CSS 类，消除 `style.css` 与 `style_young.css` 的选择器覆盖与 `!important` 堆砌，使页面在移动端、平板和宽屏显示器下保持弹性响应。

- **验收标准**：
  1. `docs/index.html` 中的数十处 `style="..."`（特别是存储超级周期卡片、图表网格、妖股鉴定器统计网格等）彻底清理归入 CSS 模块。
  2. `style.css` 与 `style_young.css` 逻辑统一，无无意义的属性重复与优先级污染。

### User Story 4 - 金融级数据对齐与等宽排版 (Priority: P2)
作为高频查阅回测数据与行情的投资者，我希望所有表格与指标卡片的数值（现价、涨跌幅、Sharpe、Alpha t值、回撤）全部采用等宽数字（`font-variant-numeric: tabular-nums`），表格具备粘性表头与平滑横向滚动，避免数字跳动。

- **验收标准**：
  1. 排行榜、自选股列表、模拟盘明细表、存储回测数据指标的数值均应用等宽数字，纵向小数点对齐整齐。
  2. 现有老年友好大字号（`.buy-today-card-name` 22px，`.market-temp-value` 28px）与免责声明 100% 保持原有语义与契约。

---

## 3. 功能契约与测试兼容性门禁 (Functional Requirements & Guardrails)

- **FR-001**: 必须 100% 通过现有全量前端测试集（共 **6 个文件 / 50 个用例**）：
  - `tests/test_frontend_v25.py`
  - `tests/test_frontend_report_ui.py`
  - `tests/test_frontend_watchlist_regions.py`
  - `tests/test_frontend_watchlist_search.py`
  - `tests/test_frontend_paper_manifest.py`
  - `tests/test_frontend_theme_contract.py`（018 新增：双主题 / 金融数字 / 响应式契约）
- **FR-002**: 必须保留所有核心 DOM 锚点：`buy-today-section`、`market-temp-bar`、`ranking-section`（同时存在于 `id` 与 `class`）、`analysis-observation`、`analysis-observation-status`、`analysis-observation-reason`、`watchlist-filter`、`watchlist-search-input`、`paper-compare-tbody` 等。
- **FR-003**: 严禁在免责声明或短线观察区域出现“买入”、“卖出”、“BUY”、“SELL”字样，恪守学术合规。
  - **判定范围**：`docs/index.html` 与 `docs/assets/app.js` 两文件全文（与 `test_frontend_report_ui.py` 现有断言口径一致，非仅限免责声明区块）。
  - **禁用词表**：`{买入, 卖出, BUY, SELL}`，其中英文**区分大小写**（小写的 `buy-today-section` 等既有标识符不受影响）。
  - **自洽性**：`买卖`（如必须保留的合规文案“研究参考，不构成买卖建议”）**不在**禁用词表内，二者不冲突。
- **FR-004**: 页面无依赖外部重型框架（无 React/Vue 编译打包依赖），保持纯原生 HTML/CSS/Vanilla JS，配合 ECharts 5.5.1 CDN，启动即跑。
  - **例外**：通过 CDN `<script>` 引入的 ECharts 运行时属于允许的第三方库，不视为“重型框架依赖”；但不得为其引入任何构建/打包步骤。

## 4. 实现期补充要求 (Implementation Addenda)

**来源**：`checklists/frontend.md` 中标记为 `[Gap]` 的要求质量检查项。本节把实现中已经落地、但 §2/§3 原先未定义的要求补写为正式契约；新增于 2026-09-15。

- **FR-005 首屏主题引导（防 FOUC）**：`docs/index.html` 与 `docs/portfolio.html` 必须在 `<head>` 内、**样式表之前**内联执行主题引导脚本，读取 `localStorage['fintech-theme']` 并写入 `document.documentElement` 的 `data-theme`，保证首屏不出现主题闪烁。
- **FR-006 存储容错**：引导脚本与主脚本对 `localStorage` 的读写**必须各自 try/catch 兜底**。存储不可用（隐私模式 / 被禁用 / 配额耗尽）时回落到默认暗色，且异常**不得中断** `DOMContentLoaded` 中后续的导航绑定与数据加载。
- **FR-007 主题跨页与可访问性契约**：主题偏好使用唯一存储键 `fintech-theme`，在 `index.html` 与 `portfolio.html` 之间共享。两页切换控件的文案节点类名必须为 `theme-toggle-text`（JS 查询类名须与标记一致），并同步维护 `aria-pressed` 与 `aria-label`。
- **FR-008 主题→图表联动范围**：主题切换必须遍历全部已创建且未销毁的 ECharts 实例（登记于 `themedChartInstances()`：K 线 `state.chart`、大盘对比 `state.indexChart`）。模拟盘净值曲线为内联 SVG，其网格线与刻度颜色必须由 CSS Token 驱动（`--border-color` / `--text-muted`），不得硬编码色值。不得保留指向未被赋值实例的死引用。
- **FR-009 粘性表头与滚动契约**：排行榜、模拟盘明细、自选股编辑表必须为 `thead th` 声明 `position: sticky; top: 0` 与不透明底色。滚动容器（`.ranking-table-wrap` / `.paper-table-wrap`）必须同时提供横向滚动与纵向 scrollport（`overflow: auto` + `max-height`）——仅有 `overflow-x: auto` 时粘性表头不会生效。窄屏策略：排行榜沿用既有卡片化重排，模拟盘明细沿用容器内横滚，两者不得并存第二套策略。
- **FR-010 响应式权威断点**：权威断点集合为 **393 / 768 / 1024 / 1440 / 1920px**；新增响应式规则一律落入该集合，不得再引入散落数值（历史遗留的 420 / 500 / 700 / 767 / 899 / 900 保留兼容并逐步收敛）。393px 及以下可收紧留白，但**不得下调**老年友好大字号契约（`.buy-today-card-name` 22px、`.market-temp-value` 28px）。
- **FR-011 资产版本化**：修改 `docs/assets/` 下的 CSS/JS 后，必须同步提升引用处的版本查询串（`?v=YYYYMMDD_...`），避免浏览器命中旧缓存。
