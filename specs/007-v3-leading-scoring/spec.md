# Feature Specification: StockDashboard 3.0 前沿信息主导评分引擎与双轨对比

**Feature Branch**: `007-v3-leading-scoring`

**Created**: 2026-08-18

**Status**: Draft

**Input**: User description: "可以开始吧我觉得可以先不急做两份然后进行比对，就叫你说的这个新的叫做3.0好了"

## 背景 (Background)

**核心矛盾**：
- 2.0 版的最终总分公式为 `total_score = 0.5 * technical_composite + 0.5 * fundamental_score`。
- 传统基本面（财报 PE/PB/ROE）占了 50% 的决定权，而前沿领先指标仅在 technical 中占 10%，被严重稀释。
- 财报是滞后 1~3 个月的“后视镜”，师叔瓶颈投资与 claw-quant 的核心真谛是用**前沿高频领先信息（现货价格/海关出口/订单流）抢先识别供需拐点**。
- 为了平滑过渡与量化验证，用户要求**不要直接覆盖 2.0，而是做出 3.0 新引擎，生成两份榜单进行深度比对**。

**范围界定**：
1. 实现 3.0 评分引擎 `src/analysis/scoring_v3.py`：
   - 前沿领先指标（45%）+ 历史相似走势胜率（30%）+ 技术形态支撑（25%）；
   - 传统财报退化为“排雷门禁”（资不抵债/严重亏损等直接一票否决淘汰，通过则不加分）；
   - 同样施加 20日波动率/回撤的风险调整。
2. 保持 2.0 与 3.0 双轨并存：
   - 2.0 榜单：`docs/data/analysis/ranking.json`
   - 3.0 榜单：`docs/data/analysis/ranking_v3.json`
3. 自动化比对工具 `tools/compare_v2_v3.py`，生成比对分析报告 `reports/v2_vs_v3_comparison.md`。
4. 前端 CLI 看板支持 `[v3.0 前沿驱动]` 与 `[v2.0 传统财报]` 双轨一键无缝切换。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 3.0 前沿主导评分计算 (Priority: P1)
项目所有者需要一套真正以前沿供需拐点为主导的评分引擎，让现货与海关走强、动能加速的标的获得显著机会分优势，同时对财务暴雷标的进行一票否决。

**Acceptance Scenarios**:
1. **Given** 标的 A 具备领先指标加速/反转信号，标的 B 无领先信号（中性），其余指标一致，**When** 计算 3.0 综合分，**Then** A 的综合分显著大幅高于 B（差值 > 10 分）。
2. **Given** 标的 C 财务资不抵债（资产负债率 > 90% 且净利亏损），**When** 3.0 门禁检查，**Then** 排雷未通过，综合分置 0 或标记 rejected。
3. **Given** 标的 D 财务正常，**When** 3.0 计算，**Then** 财报不额外产生正向加分，不扭曲前沿排名。

---

### User Story 2 - 双轨榜单生成与比对分析 (Priority: P1)
项目所有者需要系统同时生成 2.0 与 3.0 两个版本的榜单，并输出一份清晰详实的量化比对报告，证明 3.0 如何修正了 2.0 的“后视镜偏差”。

**Acceptance Scenarios**:
1. **Given** 202 只标的最新行情与分析数据，**When** 运行比对工具，**Then** 成功生成 `ranking.json` (2.0) 与 `ranking_v3.json` (3.0)。
2. **When** 比对两份榜单，**Then** 输出 `reports/v2_vs_v3_comparison.md`，包含：Top 10 差异、最大上升标的及原因（前沿供需驱动）、最大下降标的及原因（历史财报假象）、换位统计与分析。

---

### User Story 3 - 前端 CLI 双轨榜单切换 (Priority: P2)
在前端 CLI 终端界面上，用户可以在排行榜顶部清晰地切换“v3.0 前沿驱动”与“v2.0 传统财报”，并直观看到排名的动态变化。

**Acceptance Scenarios**:
1. **Given** 排行榜页面，**When** 默认打开，**Then** 呈现 v3.0 前沿驱动榜单，提示符显示 `[v3.0-leading]`。
2. **When** 点击 `[v2.0 传统财报]`，**Then** 无刷新切换为 2.0 遗留榜单，提示符变为 `[v2.0-legacy]`。

## Requirements

- **FR-001**: 建立 `src/analysis/scoring_v3.py`，实现 `compute_composite_score_v3` 与 `fundamental_safety_gate`。
- **FR-002**: 3.0 机会分权重写死为：`leading_score` 0.45, `forecast_score` 0.30, `technical_score` 0.25。
- **FR-003**: 建立 `tools/compare_v2_v3.py`，自动输出 3.0 榜单与比对 Markdown 报告。
- **FR-004**: 前端 `docs/index.html` 与 `docs/assets/app.js` 支持拉取并切换 `ranking_v3.json` 与 `ranking.json`。
- **FR-005**: 编写完整单元测试，新增代码行覆盖率 100%。

## Success Criteria

- **SC-001**: 3.0 评分公式中前沿信息权重从 10% 提升至 45%，传统财报正向权重降为 0%（仅作安全门禁）。
- **SC-002**: 生成详尽的 `reports/v2_vs_v3_comparison.md`，清晰呈现 2.0 vs 3.0 前十名变化及驱动逻辑。
- **SC-003**: 浏览器中可通过 CLI 胶囊按钮无缝切换 2.0 / 3.0 榜单。
