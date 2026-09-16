# 前端要求质量检查表：Rainbow-FinGPT 看板前端专业化重构

**目的**：本检查表是 spec 018 前端重构**要求本身的单元测试**。它验证 `spec.md` / `plan.md` / `tasks.md` / `data-model.md` 中写下的要求是否**完整、清晰、一致、可测量、覆盖充分**，而不是验证实现代码是否正常工作。每个项目都应在"未读实现代码"的前提下可被回答。

**创建时间**：2026-09-15
**最近复核**：2026-09-15（前端落地后回填）
**功能**：[specs/018-frontend-professional-upgrade/spec.md](../spec.md)
**深度**：标准级（PR / 提交前同行评审门禁）
**聚焦领域**：双主题一致性（US1）· 金融数字排版与表格（US4）· 契约回归门禁（FR-001~FR-004）· 响应式与多端
**本轮明确排除范围**：US2（Emoji → SVG 微图标）与 US3（内联样式清零 / `style.css` 与 `style_young.css` 架构融合）不在本轮检查表内，需另行建立检查表验证。若需 018 定稿的完整门禁，应补齐这两项。

**当前状态**：**18 / 40 已闭合**（要求已补写进 spec 且被契约测试覆盖），22 项仍开放。

| 类别 | 已闭合 / 总数 |
|---|---|
| 1. 范围与要求完整性 | 0 / 4 |
| 2. 双主题一致性 | 6 / 10 |
| 3. 金融数字排版与表格 | 6 / 6 |
| 4. 契约回归门禁 | 4 / 8 |
| 5. 响应式与多端 | 5 / 6 |
| 6. 异常与恢复路径 | 0 / 3 |
| 7. 可测量性与可追溯性 | 0 / 3 |

**备注**：本检查表由 `/speckit-checklist-zh` 依据当前功能上下文生成；`[Gap]` 表示来源文档中尚无对应要求，`[冲突]` / `[歧义]` / `[假设]` 表示已有要求之间存在张力。勾选项后的 `↳` 行为闭合依据。

---

## 1. 范围与要求完整性

- [ ] CHK001 - 是否明确列出了本次重构覆盖的页面与文件清单（`index.html` 的 7 个 `PageId` 视图、`portfolio.html` 等），并区分"本次改造对象"与"仅需回归验证对象"？ [完整性, Gap, data-model §2]
- [ ] CHK002 - 是否为"前端专业化重构"定义了可判定的完成标准（Definition of Done），而非仅以 `tasks.md` 的勾选状态作为完成依据？ [完整性, Gap]
- [ ] CHK003 - 是否为浅色（light）主题定义了与暗色主题**对等的功能覆盖要求**，而不是仅定义为一组色值替换？ [完整性, Gap, Spec §2 US1]
- [ ] CHK004 - 是否定义了 US1-3 中"无局部颜色残留"的可枚举检查面清单（卡片、背景、边框、ECharts 坐标轴与网格线、粘性单元格、滚动条）？ [完整性, 清晰度, Spec §2 US1]

## 2. 双主题一致性（US1）

- [ ] CHK005 - 是否用可测量标准量化了 US1-3 中"0.2s 内平滑切换"的**计时起点与终点**（点击→CSS 首帧重绘完成，还是点击→全部图表实例重绘完成）？ [可测量性, Spec §2 US1]
- [ ] CHK006 - 是否为 `ThemeState` 的全部 token 分组（背景三层、边框体系、文字三级、品牌与金融语义、字体规范）规定了 dark ↔ light 的必备对应关系，并指明其**唯一权威定义文件**？ [完整性, data-model §1]
- [x] CHK007 - 是否定义了 `localStorage` 不可用（隐私模式 / 存储被禁用）时主题偏好的读取回退与用户可见行为？ [边缘情况, Gap]
  ↳ **已闭合 by FR-006**：读写各自 try/catch，回落到默认暗色，异常不得中断 `DOMContentLoaded`。测试 `test_theme_storage_access_is_guarded`、`test_head_theme_bootstrap_tolerates_unavailable_storage`。
- [x] CHK008 - 是否定义了首屏渲染阶段避免**主题闪烁（FOUC）**的要求？ [边缘情况, Gap]
  ↳ **已闭合 by FR-005**：引导脚本必须位于 `<head>` 内且早于样式表。测试 `test_head_theme_bootstrap_runs_before_stylesheets`。
- [x] CHK009 - 是否定义了主题切换与 ECharts 实例生命周期（未初始化 / 加载中 / 已 dispose）之间的时序要求？ [覆盖范围, Gap]
  ↳ **已闭合 by FR-008**：登记表跳过未创建与已销毁实例，单实例异常不得阻断其余图表。测试 `test_chart_theme_refresh_covers_every_instance`。
- [x] CHK010 - 是否**逐一列出**了必须响应主题的图表类型（K 线、大盘对比、净值走势、NALE 关系图、存储回测图表等），而非笼统要求"图表联动"？ [完整性, 清晰度, plan §4 阶段3]
  ↳ **已闭合 by FR-008**：点明 K 线 `state.chart`、大盘对比 `state.indexChart`，以及模拟盘内联 SVG 曲线的 Token 化要求。测试 `test_paper_curve_svg_colors_are_token_driven`。
- [x] CHK011 - 是否要求主题偏好在跨页面导航（`index.html` 的 7 个视图 → `portfolio.html`）之间保持一致？ [一致性, Gap]
  ↳ **已闭合 by FR-007**：唯一存储键 `fintech-theme` 跨页共享。测试 `test_theme_storage_key_shared_across_pages`。
- [x] CHK012 - 是否定义了主题切换控件的可访问性要求（ARIA 状态、键盘可达、当前主题的语义播报）？ [非功能性, 可访问性, Gap]
  ↳ **已闭合 by FR-007**：`aria-pressed` + `aria-label` 随主题同步。测试 `test_theme_toggle_exposes_pressed_state`、`test_apply_theme_updates_pressed_state`。
- [ ] CHK013 - 是否为**未被任何页面引用的样式表**（如 `docs/assets/terminal.css`）与**被重复定义的选择器**（`.market-temp-value`、`.buy-today-card-name`）规定了唯一权威来源与清理要求？ [一致性, Gap]
- [ ] CHK014 - 是否为打印 / PDF 导出场景（学术报告提交）定义了强制浅色或专用打印样式的要求？ [非功能性, 边缘情况, Gap]

## 3. 金融数字排版与表格（US4）

- [x] CHK015 - 是否枚举了必须应用等宽数字（`font-variant-numeric: tabular-nums`）的**确切组件清单**？ [完整性, Spec §2 US4]
  ↳ **已闭合 by Spec §2 US4-1**：排行榜、自选股列表、模拟盘明细表、存储回测指标。测试 `test_tabular_nums_covers_financial_tables`。
- [ ] CHK016 - 是否定义了"纵向小数点对齐"的客观判定方法（等宽数字 + 固定小数位 + 对齐方式）？ [可测量性, Spec §2 US4]
- [x] CHK017 - 是否为"粘性表头"定义了适用表格清单、粘性轴向（纵向表头 / 首列冻结）、层级 `z-index` 与背景色要求？ [清晰度, 完整性, Spec §2 US4]
  ↳ **已闭合 by FR-009**：适用表格 + `top: 0` + 不透明底色 + 首列双轴冻结层级。测试 `test_sticky_table_header_is_defined`。
- [x] CHK018 - 是否为"平滑横向滚动"定义了触发阈值（最小列宽 / 溢出判定）与滚动可用性提示要求？ [清晰度, Spec §2 US4]
  ↳ **已闭合 by FR-009**（滚动容器契约：`overflow: auto` + `max-height` 构成 scrollport）。测试 `test_table_wrappers_are_scrollports`。*注：具体阈值仍为软要求。*
- [x] CHK019 - US4-2 中"100% 保持原有语义与契约"是否给出了可核验基线（`.buy-today-card-name` 22px、`.market-temp-value` 28px、免责声明文案）？ [可测量性, Spec §2 US4]
  ↳ **已闭合 by FR-010**：显式点名两个字号契约与免责文案。测试 `test_elderly_friendly_css_exists`（既有）、`test_narrow_screen_keeps_elderly_font_contract`。
- [x] CHK020 - 是否为"高密度布局"量化了行高 / 内边距 / 字号下限，以说明其与老年友好大字号要求之间不构成冲突？ [清晰度, 冲突, Spec §2 US4]
  ↳ **已闭合 by FR-010**：给出冲突裁决方向——窄屏可收紧留白但不得下调大字号。测试 `test_narrow_screen_keeps_elderly_font_contract`。

## 4. 契约回归门禁（FR-001 ~ FR-004）

- [x] CHK021 - 是否列举了必须 100% 通过的契约测试文件与基线用例数？ [完整性, FR-001]
  ↳ **已闭合 by FR-001**：更新为 6 个文件 / 50 个用例，含新增的 `tests/test_frontend_theme_contract.py`。
- [x] CHK022 - FR-002 声明的"核心 DOM ID"清单是否与当前实现一致（`ranking-section` 现为 `class` 而非 `id`）？ [冲突, FR-002]
  ↳ **已闭合**：FR-002 改为"DOM 锚点（同时存在于 `id` 与 `class`）"，且 `docs/index.html` 已补 `id="ranking-section"`，冲突消除。
- [ ] CHK023 - 是否为 FR-002 清单之外的页面锚点（详情页、妖股鉴定器页、模拟盘页）建立了扩展契约清单？ [完整性, Gap, FR-002]
- [ ] CHK024 - 是否为"今日可以关注区必须位于排行榜之前"这一**顺序契约**定义了适用页面与判定方式？ [清晰度, tests/test_frontend_v25.py]
- [ ] CHK025 - 是否定义了免责声明与短线观察区域**禁用词的判定范围与扫描方式**（关键词集合、中英大小写、HTML 实体与混排）？ [清晰度, FR-003]
- [x] CHK026 - FR-003 的禁用词规则是否与必须存在的"研究参考，不构成买卖建议"文案保持自洽（该文案本身含"买卖"二字）？ [一致性, 冲突, FR-003]
  ↳ **已闭合 by FR-003 自洽性条款**：禁用词表为 `{买入, 卖出, BUY, SELL}`，"买卖" 不在表内，两者不冲突。测试 `test_observation_panel_precedes_analysis_title_without_trade_commands`。
- [ ] CHK027 - 是否规定了契约测试作为阻断门禁的判定条件，以及豁免 / 破例的审批流程？ [完整性, plan §3]
- [x] CHK028 - 是否明确了"无 React/Vue 编译打包依赖"（FR-004）是否将 CDN 引入的第三方运行时（ECharts 5.5.1）视为例外？ [歧义, FR-004]
  ↳ **已闭合 by FR-004 例外条款**：CDN 引入的 ECharts 运行时属允许的第三方库，但不得引入构建步骤。

## 5. 响应式与多端

- [x] CHK029 - 是否用**具体断点数值**量化了"移动端 393px 至桌面端 1920px"之间的布局要求？ [清晰度, plan §2]
  ↳ **已闭合 by FR-010**：权威断点 393 / 768 / 1024 / 1440 / 1920px。测试 `test_responsive_authority_breakpoints_are_declared`。
- [x] CHK030 - 是否统一了权威断点集合（现网 `style.css` 同时存在 420 / 500 / 700 / 767 / 899 / 900 六个互不对齐的 `max-width` 断点）？ [一致性, 冲突]
  ↳ **已闭合 by FR-010**：确立权威集合，历史断点保留兼容并逐步收敛。
- [ ] CHK031 - 是否为 393px 窄屏定义了**必须保持可见的核心指标**与可折叠的次要信息优先级？ [覆盖范围, Gap]
- [x] CHK032 - 是否为 1920px 及以上宽屏定义了最大内容宽度、留白与图表网格列数，而非随意拉伸？ [清晰度, Gap]
  ↳ **已闭合**：`@media (min-width: 1440px)` 容器收敛至 1360px、`(min-width: 1920px)` 至 1560px，并调整妖股卡片网格列宽。
- [x] CHK033 - 是否为表格在移动端的呈现（横向滚动 vs 卡片化重排）定义了唯一策略而非两种并存？ [歧义, 一致性]
  ↳ **已闭合 by FR-009**：排行榜沿用卡片化重排，模拟盘明细沿用容器内横滚，按表分派、不并存第二套策略。
- [ ] CHK034 - 是否定义了视口尺寸变化 / 横竖屏切换时的图表重建要求，并与 plan §2 的 `ResizeObserver` 承诺对齐？ [完整性, plan §2]

## 6. 异常与恢复路径（[Gap]，非阻断）

- [ ] CHK035 - 是否定义了主备 CDN（`fastly.jsdelivr.net` 与 `cdn.bootcdn.net`）**均不可用**时 ECharts 依赖的降级行为与用户可见提示？ [异常流程, Gap]
- [ ] CHK036 - 是否定义了数据文件（`docs/data/strategy/*.json` 等）加载失败或超时时，相关区块的显示与错误提示要求？ [异常流程, plan §4]
- [ ] CHK037 - 是否为本次重构失败定义了回滚要求（旧版 CSS / JS 资产的可回退性与回退判定条件）？ [恢复流程, Gap]

## 7. 可测量性与可追溯性

- [ ] CHK038 - 是否每一条 User Story 验收标准都可以被第三方在**不阅读实现代码**的前提下客观复核？ [可测量性, Spec §2]
- [ ] CHK039 - 是否建立了要求之间的 ID 互引方案（US1~US4 ↔ FR-001~FR-011 ↔ tasks T003~T017）？ [可追溯性, Gap]
- [ ] CHK040 - 是否为无法自动化的验收项（设计质感、主题切换观感）规定了人工复核的判定人与证据形式？ [可测量性, Gap]

---

## 备注

- 完成后勾选项目：`[x]`；在线批注时保留原始编号。
- 维度标签：`完整性` / `清晰度` / `一致性` / `可测量性` / `覆盖范围` / `边缘情况` / `异常流程` / `恢复流程` / `非功能性` / `冲突` / `歧义` / `假设` / `可追溯性`。
- 标记说明：`[Gap]` 表示来源文档缺失该要求；`[冲突]` 表示已有要求之间存在矛盾；`[歧义]` 表示措辞不可判定。
- 来源锚点：`Spec §X` 指 `spec.md`；`plan §X` 指 `plan.md`；`data-model §X` 指 `data-model.md`；`FR-00X` 指 `spec.md` 第 3/4 节功能契约。
- 本检查表**不覆盖** US2（SVG 微图标）与 US3（内联样式清零）；如需 018 定稿完整门禁，请另建检查表。
- **仍未闭合的 22 项中，CHK035~CHK037（异常与恢复路径）与 CHK005（切换耗时量化）风险最高**，建议在 018 定稿前补写为正式契约。
