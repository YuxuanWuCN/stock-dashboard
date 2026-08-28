# Feature Specification: LLM 情绪信号度量与数据口径修复（Phase 0）

**Feature Branch**: `004-sentiment-signal-fix`

**Created**: 2026-08-15

**Status**: Draft

**Input**: User description: "修复 LLM 情绪信号系统性反转：离线重算 sentiment_score 到实际涨跌方向的对齐率（当前约 34.7% 低于抛硬币），定位反转根因（新闻日期错位/多空映射反了/标签错误），修复后方向对齐率 >50% 并回归验证，全程可复现不伪造"

## 背景 (Background)

来源：《项目规划/07-StockDashboard-v3.0-差距分析.md》Phase 0 建议 + reports/prediction_accuracy/README.md 诚实基线。

**问题描述**：校准报告（reports/calibration/calibration_report_20260814_181919.json）显示 LLM 情绪 alignment_rate = 0.347（144 样本）。README 据此推断"情绪信号可能被系统性反转"。Phase 2（FOI 管线）必须以可信的情绪信号为基础，故本 feature 先行诊断并修复。

**规格写作前的侦察结论（2026-08-15 静态审阅 + 数据抽查，写入假设）**：

1. **数据口径错误（根因候选 1，证据最充分）**：src/llm/generate_reports.py 的 _record_market_feedback 把 KNN **预测**的 5 日收益（forecast.return_5d_pct）当作"后续实际收益"记入市场反馈样本（其 docstring 明确写道"用相似走势预测的 5 日收益作为后续收益的近似"）。因此 34.7% 度量的是"情绪 vs KNN 预测"的一致性，**与"情绪 vs 实际涨跌"无关**——README 的"信号反转"推断前提不成立。
2. **度量口径错误（根因候选 2）**：src/market_feedback.py compute_summary 的 alignment_rate = 方向一致样本数 / 全样本数，分母包含 31 个无情感分样本与 |score|<0.1 的中性样本（这些样本按设计 aligned=False），系统性拉低数字。
3. **真实方向性未知**：现有样本中的 ret 字段来自预测值，无法据此判断情绪信号的真实方向性。真实结论必须用 K 线已实现收益离线重算（docs/data/kline/*.json 含 5 年日线，可算 event_date 后 3/5 交易日收益）。

**范围界定**：本 feature 做三件事——① 离线诊断报告（确认根因 1/2，审计日期窗口偏移）；② 数据口径修复（record_event 改用真实已实现收益，历史样本离线重算回填）；③ 度量口径修复（新增 directional_accuracy 正确定义）。**不做**：词典/阈值/提示词的信号增强（留 Phase 2 FOI 一并处理）；若诊断最终证实信号真反转，映射修复纳入本 feature（US3 条件分支）。原始 K 线数据绝不修改（AGENTS.md）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 离线诊断报告：34.7% 到底度量了什么 (Priority: P1)

项目所有者需要一份可复现的诊断报告，明确回答三个问题：① 市场反馈样本的"实际收益"来源是否可信（预测值还是已实现值）；② alignment_rate 口径是否公平（分母是否含无方向样本）；③ 用真实 K 线收益重算后，情绪方向与真实涨跌方向的关系（正相关/无关/反转）。

**Why this priority**: 没有诊断结论就无法决定修什么。修复方向错误（比如盲目"翻转映射"）会把一个口径缺陷变成真正的信号错误，P1 是地基。

**Independent Test**: 纯离线运行诊断脚本（读 market_feedback.json + kline JSON，零网络），输出诊断报告，独立交付价值（立即知道 34.7% 的真相）。

**Acceptance Scenarios**:

1. **Given** docs/data/llm/market_feedback.json（144 样本）与 docs/data/kline/*.json，**When** 运行诊断，**Then** 输出报告含：ret 字段来源审计（指出 ret_5d_pct 来自 forecast.return_5d_pct 的代码位置与样本证据）、alignment_rate 分母构成分解（有分/无分/中性/方向不一致各多少）
2. **Given** 同一数据，**When** 按 event_date 从 K 线计算真实 3/5 日已实现收益并重算方向一致率，**Then** 输出"情绪 vs 真实收益"的方向统计表（正分样本上涨占比、负分样本上涨占比、样本数），并给出结论段：正相关 / 无关 / 反转（含置信区间）
3. **Given** 缺失 K 线或收益窗口不足的样本，**When** 计算真实收益，**Then** 标记为不可算并计入报告，绝不编造

---

### User Story 2 - 数据口径修复：真实收益入库 (Priority: P1)

record_event 的市场反馈样本必须记录**真实已实现收益**（由 event_date 之后 3/5 个交易日的收盘价计算），KNN 预测值不得再作为"实际收益"；历史样本离线重算回填，新旧对比留存。

**Why this priority**: 数据口径是一切下游评估（RLSP 奖励、软标签、校准）的地基。错的地基上叠多少评估都是错的；这是 Phase 0 的核心修复。

**Independent Test**: 用合成 K 线 + 已知未来收益的夹具验证 record_event 写出的 ret_3d/ret_5d 与手算一致；用真实数据重跑回填后，回填前后对比报告可查。

**Acceptance Scenarios**:

1. **Given** 一只合成标的：event_date=t，t+1..t+5 收盘价已知（夹具），**When** 调用新的收益计算函数，**Then** ret_5d = (close[t+5]-close[t])/close[t]*100（口径写死并手算复核一致），数据不足返回 None
2. **Given** 修改后的 record_event 调用链，**When** 传入 KNN 预测值，**Then** 预测值只写入 forecast 相关字段，绝不落入 ret_3d/ret_5d 实际收益字段
3. **Given** 144 条历史样本与 K 线数据，**When** 运行回填脚本，**Then** 幂等重算（两次运行结果一致）、回填前快照留存、不可算样本显式标注
4. **Given** 无前视注入测试（用 event_date 之前的 K 线数据计算），**When** 运行，**Then** 断言必须触发失败（收益只能用 event_date 之后的交易日）

---

### User Story 3 - 度量口径修复：directional_accuracy (Priority: P2)

compute_summary 新增"决定性样本方向准确率" directional_accuracy = 方向一致数 / 决定性样本数（|sentiment_score| >= 0.1 且有真实收益的样本）；旧 alignment_rate 字段保留并标注其含义，避免破坏消费方。

**Why this priority**: 依赖 US1/US2 的诊断与数据修复完成，故 P2；它是校准报告数字可信度的直接来源。

**Independent Test**: 用构造的样本集（含无分/中性/方向一致/不一致四类）验证新指标等于手算值；旧字段仍存在。

**Acceptance Scenarios**:

1. **Given** 构造样本集（如 10 条：3 无分、2 中性、3 一致、2 不一致），**When** compute_summary，**Then** directional_accuracy == 3/5 == 0.6，alignment_rate 仍按旧定义输出，两者并存
2. **Given** 决定性样本数为 0，**When** compute_summary，**Then** directional_accuracy 为 None（不除零、不伪造）
3. **Given** 修复后的真实数据，**When** 重算汇总，**Then** 校准报告（tools/calibration.py 消费方）能读到新字段且不报错

---

### User Story 4 - 验证与门禁：与抛硬币基线对比 (Priority: P3)

修复完成后用真实数据重算方向准确率，与 50% 抛硬币基线对比（含置信区间），结论（信号方向性 + 是否需要映射修复）写入报告归档；全链质量门禁通过。

**Why this priority**: 收尾验证；结论决定 Phase 2 FOI 是否可以直接采用该信号。

**Independent Test**: 运行验证脚本 + 三级质量门禁（small/medium/heavy）全绿，验证报告归档。

**Acceptance Scenarios**:

1. **Given** 回填后的真实样本，**When** 重算 directional_accuracy，**Then** 报告给出：样本数、准确率、二项分布 95% 置信区间、与 50% 的对比结论（显著高于/无显著差异/显著低于），不夸大
2. **Given** 诊断结论为"信号真反转"，**When** 执行 US3 条件分支（映射修复），**Then** 修复后重算 > 50% 且置信区间不覆盖 50%；若诊断为口径缺陷，则不修改映射并如实记录
3. **Given** 全部代码与测试，**When** 运行质量门禁，**Then** small → medium → heavy 全绿，新增代码行覆盖 100%

---

### Edge Cases

- **样本的 event_date 无对应 K 线**（代码改名/退市）→ 不可算，标注，不编造
- **收益窗口跨越停牌/长休市** → 按交易日数计算（3/5 个交易日），非自然日；不足则 None
- **event_date 是 K 线最后一日**（窗口不足）→ None
- **回填脚本重复运行** → 幂等（快照仅首次创建，结果覆盖式更新）
- **旧字段消费方兼容** → alignment_rate 保留原定义与字段名
- **样本量小**（决定性样本 < 30）→ 报告明确标注统计功效不足，只给描述性结论

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供离线诊断入口（如 tools/diagnose_sentiment_alignment.py），读 market_feedback.json 与 kline JSON，零网络依赖，输出诊断报告（根因审计 + 真实方向统计 + 结论）
- **FR-002**: 诊断 MUST 覆盖三项审计：ret 字段来源（预测 vs 已实现）、alignment_rate 分母构成、event_date 与收益窗口的日期偏移
- **FR-003**: 系统 MUST 提供真实收益计算函数（event_date 后 N 个交易日收盘价口径），N ∈ {3, 5}；窗口不足返回 None
- **FR-004**: record_event 的 ret_3d/ret_5d MUST 只接受真实已实现收益；KNN 预测值 MUST 只写入预测字段，不得冒充实际收益
- **FR-005**: 系统 MUST 提供历史样本回填脚本：幂等、首次运行前快照原文件、不可算样本显式标注、输出回填前后对比
- **FR-006**: compute_summary MUST 新增 directional_accuracy（决定性样本口径：|score| >= 0.1 且有真实收益）；旧 alignment_rate 字段 MUST 保留原定义
- **FR-007**: 系统 MUST 保证无前视：收益计算只用 event_date 之后的交易日数据；泄漏注入测试必须能触发失败
- **FR-008**: 系统 MUST 不伪造数据：任何不可算场景输出 None + 原因标注（与项目既有约定一致）
- **FR-009**: 全部新增/修改 MUST 有 pytest 覆盖（正常/边界/缺失/失败路径），新代码行覆盖 100%
- **FR-010**: 验证结论 MUST 写入报告（样本数、准确率、95% 置信区间、与 50% 基线对比），按 AGENTS.md 第 3 条独立复核并记录局限
- **FR-011**: 原始 K 线数据 MUST 不被修改（只读），回填只作用于派生数据 market_feedback.json

### Key Entities

- **FeedbackSample（修订）**: 市场反馈样本；新增/明确字段：realized_ret_3d_pct / realized_ret_5d_pct（真实已实现收益）、forecast_ret_5d_pct（原预测值，独立保存）、ret_3d_pct / ret_5d_pct（指向真实收益，向后兼容）
- **DiagnosisReport**: 诊断报告；属性：ret 来源审计、分母构成、真实方向统计表、结论与置信区间
- **AlignmentSummary（修订）**: compute_summary 输出；新增 directional_accuracy 与决定性样本数，保留 alignment_rate

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 诊断报告明确回答"34.7% 是否代表信号反转"，结论以重算数据为准并给出置信区间
- **SC-002**: 回填后 directional_accuracy 的样本构成可审计（决定性样本数、无分样本数、不可算样本数全部列出）
- **SC-003**: 修复后"情绪 vs 真实收益"的方向准确率结论与 50% 基线的对比清晰（显著高于/无差异/显著低于三选一，含区间），如实入档
- **SC-004**: 新增代码行覆盖 100%，质量门禁 small → medium → heavy 全绿
- **SC-005**: 回填脚本幂等验证：连续两次运行产出逐字节一致的结果文件
- **SC-006**: 诊断与验证报告归档于 reports/ 下，供 Phase 2 FOI 立项引用

## Assumptions

- **34.7% 的信号反转是度量/口径问题而非真实反转**（侦察证据：ret 来源是 KNN 预测值；正分样本 57.4% vs 负分 42.1% 的方向差为正）——但以诊断报告的重算结论为准，不预设
- **真实收益口径**：ret_N = (close[t+N] - close[t]) / close[t] × 100，t 为 event_date 所在交易日收盘（前复权数据按项目现有口径）
- **event_date 与 K 线对齐**：按 docs/data/kline/{code}.json 的 dates 定位；样本 code 找不到 K 线 → 不可算
- **中性阈值**：|score| < 0.1 视为无方向（沿用 generate_soft_label 的 0.1 阈值）
- **回填时机**：一次性脚本 + 可重跑；不改变每日流水线的写入顺序（record_event 修复后自然产出正确数据）
- **信号增强（词典/阈值/提示词）留 Phase 2**：本 feature 只修数据与度量口径；若诊断证实真反转，映射修复在 US3 条件分支内执行
