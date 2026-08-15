# Feature Specification: Fama-MacBeth 多因子引擎（Phase 1）

**Feature Branch**: `003-fama-macbeth-engine`

**Created**: 2026-08-15

**Status**: Draft

**Input**: User description: "在 build_ranking.py 中集成 Fama-MacBeth 两阶段回归多因子引擎（Carhart 4 因子：MKT/SMB/HML/MOM）：建立日频 A 股因子数据层，运行时间序列回归输出每日 Alpha p 值与信息比率 IR，硬约束 Alpha p<0.05 且 IR>=0.3 才入选激进组合候选，因子 Beta 与残差 Alpha 零重叠，模块达到 100% 测试覆盖率"

## Clarifications

### Session 2026-08-15

- Q1: FR-001 因子数据来源（付费库/免费源/手工 CSV/仅夹具）？ → A: **用户手工提供 CSV（CSMAR/RESSET 导出）**。开发与测试期使用夹具 CSV（离线可复现），真实 CSV 接入时按约定的列格式（日期 + MKT/SMB/HML/MOM + 来源版本标识）加载；CSV 详细格式约定在 plan 阶段定稿
- Q2（范围）：第一个 speckit feature 范围？ → A: 仅 Phase 1 Fama-MacBeth 多因子引擎（因子数据层 + 两阶段回归 + Alpha/IR 门控），Phase 0/2/3/4 各自另开 feature

## 背景 (Background)

来源：《本人研究成果/stock-dashboard-v3-plan.pdf》（StockDashboard V3.0 Blueprint，2026-08-14）Phase 1，配套差距分析《项目规划/07-StockDashboard-v3.0-差距分析.md》。

v3.0 蓝图 Engine 2（Serenity Layer 2）要求：对通过定性过滤的标的执行 **Fama-MacBeth 两阶段回归**（Carhart 4 因子 MKT/SMB/HML/MOM），以"统计显著 + 经济显著"双重硬约束筛选**真正的 Alpha**：

1. **统计显著性**：残差 Alpha 的 p < 0.05。p >= 0.05 说明超额收益可能是随机游走或纯因子暴露，降级为 Watchlist。
2. **经济显著性（信息比率）**：IR = alpha / sigma(residual) >= 0.3。IR < 0.3 说明 Alpha 的安全边际不足以覆盖交易摩擦，拒绝。

**当前现状（差距分析结论）**：v2.6.0 排行榜机会分 = 预测百分位 35% + 上涨概率 25% + 技术分 20% + 行业分 20%（src/analysis/config.py OPPORTUNITY_WEIGHTS），**无任何因子暴露调整**；grep "fama/macbeth/statsmodels/carhart" 全库零命中。本项目 K 线存于 docs/data/kline/*.json（akshare 缓存），**无 SQLite 因子库**。本 feature 是 v3.0 六项短板中第 1 项（无风险调整 Alpha 验证）的落地，也是唯一完全从零的模块。

**范围界定**：本 feature 只做 Engine 2 的 Phase 1 三段内容——① 因子数据层（SQLite 因子库 + 加载器）；② Fama-MacBeth 两阶段回归模块；③ Alpha/IR 硬门控接入 build_ranking.py 的激进组合候选。**不做** FOI/Chokepoint 门控（Phase 2）、ZigZag 波浪（Phase 3）、贝叶斯校准（Phase 4）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 因子数据层：可审计的日频 4 因子库 (Priority: P1)

项目所有者（学生/研究者）需要一份日频的 A 股 Carhart 4 因子（MKT/SMB/HML/MOM）数据，供后续所有回归使用。该数据层必须可审计：能回答"因子数据从哪来、覆盖到哪天、缺了哪些日期、有没有未来数据"。

**Why this priority**: 因子数据是回归的地基。数据缺失/错位/前视会污染所有下游统计结论；且它是唯一与行情抓取解耦、可先用夹具完全离线验证的环节。没有它，后续回归无从谈起。

**Independent Test**: 仅用离线夹具因子 CSV 即可验证：加载入库 → 查询完整性/对齐性/无前视断言 → 输出数据质量报告。独立交付价值：项目第一次拥有结构化的因子数据库与质量审计入口。

**Acceptance Scenarios**:

1. **Given** 一份含 MKT/SMB/HML/MOM 四列、日频、覆盖 5 年窗口的因子 CSV（夹具），**When** 执行因子入库，**Then** 生成 SQLite 因子库，表结构含日期主键与四因子列，无重复日期、无空值缺口超过可配置阈值（默认 5%）
2. **Given** 因子库与个股 K 线（docs/data/kline/*.json），**When** 对齐检查，**Then** 输出每只标的的因子覆盖区间、缺失日期清单，且所有回归窗口的因子值只使用"截至该日期"的数据（无前视断言通过）
3. **Given** 真实数据源不可用时（离线/无账号），**When** 运行主流程，**Then** 明确报错并给出可操作的提示，绝不静默使用缺失或伪造的因子值

---

### User Story 2 - Fama-MacBeth 两阶段回归：输出 Alpha p 值与信息比率 (Priority: P1)

对每只标的的 5 年日线超额收益执行两阶段回归：阶段一（时间序列）估计对 4 因子的暴露 beta；阶段二（横截面）估计因子风险溢价并计算残差 Alpha 的显著性（p 值）与信息比率（IR = alpha / sigma(residual)）。

**Why this priority**: 这是 Engine 2 的核心科学贡献——把"KNN 概率高"与"存在统计上显著的 Alpha"区分开，是蓝图 6 项短板第 1 项的直接解药。

**Independent Test**: 用人工构造的已知 Alpha 样本（夹具）验证：构造一只 beta 已知、残差已知、注入已知 alpha 的合成序列，回归结果必须还原注入值（误差在可接受容差内）；再构造一只纯因子暴露（alpha=0）序列，必须判为"无显著 Alpha"。独立交付价值：可复现的统计验证工具。

**Acceptance Scenarios**:

1. **Given** 合成序列 A（注入 alpha=0.5%/日、IR 设计为 0.5），**When** 执行两阶段回归，**Then** 估计 alpha 落在注入值 ±20% 容差内，p < 0.05，IR >= 0.3，判定为"True Alpha"
2. **Given** 合成序列 B（alpha=0，纯 MKT 暴露），**When** 执行回归，**Then** p >= 0.05 或 IR < 0.3，判定为"无显著 Alpha / 纯因子暴露"
3. **Given** 阶段一回归的 beta 估计，**When** 计算残差，**Then** 残差 Alpha 与各因子 beta 的相关性低于可配置阈值（蓝图要求"因子 Beta 与残差 Alpha 零重叠"，默认 r < 0.05），共线性诊断（VIF）输出到报告
4. **Given** 少于最小窗口长度的数据（如新股 < 1 年），**When** 回归，**Then** 输出 null 并标注原因，不伪造结果（对齐项目 KNN 的既有约定）

---

### User Story 3 - Alpha 门控接入排行榜：只有 True Alpha 进激进组合候选 (Priority: P2)

build_ranking.py 的激进组合候选必须通过 Alpha 门控（p < 0.05 且 IR >= 0.3），未通过的标的降级为 Watchlist 并记录原因；排行榜与个股详情中可见门控字段与统计结果。

**Why this priority**: 门控是把统计结论转化为实际投资决策的最后一环，价值取决于 US1/US2 是否完成，故为 P2；但它决定"排行榜是不是真的风险调整过"。

**Independent Test**: 在夹具数据上运行 build_ranking 流水线（含 mock 行情），断言：激进组合候选 = 原候选 ∩ 通过门控集合；被拒绝标的出现在 Watchlist 且原因字段非空。

**Acceptance Scenarios**:

1. **Given** 一次完整排行榜运行（夹具），**When** 构建激进组合候选，**Then** 候选只包含 alpha_gate=pass 的标的，且每只标的的 alpha/p/IR 写入个股详情 JSON
2. **Given** 全池无一通过门控，**When** 构建组合，**Then** 触发明确的降级策略（见假设：默认按原机会分回退并告警），不产生空组合、不崩溃
3. **Given** 排行榜 JSON 校验（src/analysis/schema.py），**When** 加入新字段，**Then** 校验规则同步扩展，旧字段兼容

---

### User Story 4 - 质量门禁与独立复核：100% 覆盖、零前视泄漏 (Priority: P3)

模块进入项目质量工作流：pytest 全量覆盖（蓝图 KPI：模块 100% 测试覆盖率）、防未来数据泄漏专项测试、独立可手算的小样本复核记录。

**Why this priority**: 保障可复现性与可信度（AGENTS.md 第 3 条：不能把门禁退出码当作正确性证明），是部署前收尾，故为 P3。

**Independent Test**: 运行 tools/run_quality.ps1 的 small → medium → heavy 三级门禁；人工用 Excel/手算复核至少 3 只标的的回归结果（记录于报告）。

**Acceptance Scenarios**:

1. **Given** 全部新增模块与测试，**When** 运行门禁，**Then** small/medium/heavy 全绿，新增代码行覆盖率 100%，无"跳过测试"掩盖
2. **Given** 回归模块，**When** 静态审阅与泄漏注入测试（用未来因子值污染数据），**Then** 泄漏检测断言必须触发失败，证明无前视
3. **Given** 手工构造 3 只小样本标的，**When** 手算复核 alpha/p/IR，**Then** 与模块输出一致（容差内），复核记录写入 spec 或报告

---

### Edge Cases

- **因子与 K 线日期不对齐**：停牌日、节假日差异 → 以交易日并集/交集策略明确，默认取两者交集并记录剔除数
- **新股/次新股**：数据不足最小窗口 → 输出 null + 原因（与 KNN 既有约定一致）
- **因子共线性**：MKT 与其他因子高度相关时 VIF 超阈值 → 报告警告，不静默剔除
- **极端行情窗口**（如 2015 股灾、2024 年初流动性危机）：beta 估计受异常值影响 → 报告标注窗口，提供稳健估计（如 winsorize 选项）记录于假设
- **停牌长期无成交**：收益率为 NaN → 剔除该日并用可配置阈值告警
- **组合规模不足**：通过门控数 < 组合 min_size → 降级回退策略（见假设）
- **回归性能**：全池（约 202 只 × 5 年日线）单次回归耗时超预算 → 并行化或窗口缓存（性能预算见成功标准）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 提供日频 Carhart 4 因子（MKT/SMB/HML/MOM）的加载能力，数据来源为用户手工提供的 CSV（CSMAR/RESSET 导出，2026-08-15 澄清确认；开发期以夹具 CSV 代替），CSV 须含日期列与 MKT/SMB/HML/MOM 四列及来源版本标识；加载器 MUST 对缺失列、重复日期、空值缺口超阈值（默认 5%）执行校验并明确报错
- **FR-002**: 系统 MUST 将因子数据持久化到 SQLite 因子库（项目内新建，如 docs/data/factors/factors.db），日期为主键，无重复日期
- **FR-003**: 系统 MUST 支持从 SQLite 因子库读取任意标的 5 年窗口内的因子序列，并与该标的日 K 线按交易日对齐（交集策略，记录剔除日）
- **FR-004**: 系统 MUST 执行两阶段回归：阶段一（时间序列）以个股超额收益为因变量对 4 因子回归，估计 beta；阶段二（横截面）以个股平均收益对 beta 回归，估计风险溢价与残差 Alpha
- **FR-005**: 系统 MUST 输出每只标的的回归结果：alpha、p 值、IR（= alpha / sigma(residual)）、各因子 beta、VIF 诊断
- **FR-006**: 系统 MUST 应用双重硬门控：p < 0.05 且 IR >= 0.3 判定为 "True Alpha"（通过）；否则降级 Watchlist
- **FR-007**: 系统 MUST 将门控结果写入排行榜 JSON（ranking.json）与个股详情 JSON，包含 alpha/p/IR/门控判定与拒绝原因字段，且通过 schema 校验
- **FR-008**: 系统 MUST 保证无前视：任何回归窗口的 beta/alpha 估计只用截至该时点的数据（滚动或锚定窗口）
- **FR-009**: 系统 MUST 在数据不足（少于最小窗口，默认 1 年）时输出 null 并记录原因，禁止伪造
- **FR-010**: 系统 MUST 支持离线可复现：全部测试使用夹具/合成数据，外部因子与行情请求可 mock（对齐 AGENTS.md）
- **FR-011**: 系统 MUST 在激进组合候选构建时只纳入 alpha_gate=pass 的标的；无通过者时按降级策略处理并告警
- **FR-012**: 系统 MUST 提供数据质量报告（覆盖率、缺失日期、对齐率），供每次运行审计

### Key Entities

- **FactorSeries**: 单只因子（MKT/SMB/HML/MOM）的日频序列；属性：日期、值、来源版本标识
- **FactorDatabase**: SQLite 因子库；存储全部因子序列；支持按日期区间查询与对齐
- **RegressionResult**: 单只标的的两阶段回归输出；属性：标的代码、窗口区间、alpha、p 值、IR、beta 向量（4）、VIF、样本数、收敛状态
- **AlphaGateVerdict**: 门控判定；属性：pass/reject、拒绝原因（统计不显著/经济不显著/数据不足）、关联 RegressionResult
- **RankingEntry（扩展）**: 排行榜条目新增 alpha_gate 字段组（verdict + alpha/p/IR），供前端与审计消费

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 因子库覆盖全部自选股标的的 5 年分析窗口，与 K 线交易日对齐率 >= 95%，缺失日期全部记录可查
- **SC-002**: 在人工构造的已知 Alpha 合成样本上，回归还原注入 alpha 的误差在 ±20% 内，识别准确率 100%（已知真值全部判对）
- **SC-003**: 排行榜每次运行均带 Alpha 门控字段，且不存在"通过门控却被排除在激进组合候选之外"的标的（审计一致）
- **SC-004**: 新增模块测试覆盖率 100%（蓝图 KPI），质量门禁 small → medium → heavy 全绿；泄漏注入测试必须能触发失败
- **SC-005**: 全池（约 202 只 × 5 年）单次回归流水线在 15 分钟内完成（本地开发机）
- **SC-006**: 至少 3 只标的的回归结果经独立手算复核，与模块输出一致（容差内），复核记录归档

## Assumptions

- **因子数据为日频**，与日 K 线同一交易日历；因子值在交易日结束时已知（用于无前视回归）
- **无风险利率**：A 股惯例取 10 年期国债到期收益率序列，缺失时用可配置固定近似值（如 2.5%/年），记录于配置
- **回归窗口**：锚定最近 5 年（约 1250 个交易日）单窗口估计（蓝图口径）；滚动窗口与显著性时变分析留待 Phase 4 校准
- **最小有效窗口**：默认 1 年（约 250 个交易日），可配置；低于此值输出 null
- **门控适用范围**：本 feature 只约束激进组合候选；其余组合（稳健/蓝筹等）维持现状，等 Phase 4 统一校准
- **降级策略**：通过门控数 < 组合 min_size（激进组合默认 5）时，按原机会分排名回退补齐并记录告警（比空组合更实用，且明确标注"未通过 Alpha 门控"）
- **统计实现**：时间序列回归使用 statsmodels OLS（蓝图明示）；横截面阶段手工实现 Fama-MacBeth 两步法与 t 统计量（Newey-West 校正为可选增强，记录于计划）
- **数据目录**：因子库位于 docs/data/factors/，与现有 docs/data 体系一致
- **真实因子来源**：用户手工提供 CSV（CSMAR/RESSET 导出，2026-08-15 澄清 Q1 确认）；开发与测试期使用夹具 CSV；CSV 加载器支持格式校验与来源版本标识
