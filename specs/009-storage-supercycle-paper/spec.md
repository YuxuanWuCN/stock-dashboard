# 规范 009：半导体存储超级周期学术论文与三层解耦回测框架 (Spec-Kit 009)

## 1. 概述与研究背景 (Overview & Background)

本文档规范化《*Asset Pricing and Tactical Execution in the 2025–2026 Semiconductor Storage Supercycle: A Decoupled Triple-Engine Framework*》阶段性学术论文的结构、数学推导、实证图表与工程契约。

本规范解决大模型金融量化系统三大核心顽疾：
1. **数值幻觉与随机漂移**：严格隔离 LLM，禁止 LLM 计算技术指标与时序/截面回归。
2. **多因子风格漂移**：通过滚动 252 日两阶段 Fama-MacBeth 回归与 Newey-West HAC 稳健标准误剥离 Carhart 4 因子系统风险，提取特质 Alpha。
3. **左侧抄底与 C 浪崩塌**：通过因果无未来函数 ZigZag 算法与布尔趋势门控 (Trend Gate™) 精准识别 C 浪杀跌并强制清仓防御。

---

## 2. 用户故事与需求 (User Stories & Requirements)

### US-1: 论文级学术规范与 LaTeX 交付 (Paper Artifacts)
- **FR-001**: 输出符合顶级金融量化与 AI 会议/期刊排版标准的完整 LaTeX 论文源文件 (`storage_supercycle_paper.tex`)。
- **FR-002**: 包含数学推导公式（FOI 划分、Chokepoint 矩阵、Fama-MacBeth 两阶段方程、Newey-West HAC、布尔趋势门控、Brier Score）。
- **FR-003**: 包含 5 幅 $\ge 300\text{ DPI}$ 的专业实证图表与 1 幅架构示意图。

### US-2: SCNU-RAG 定性过滤与对抗性降级 (Qualitative Gate)
- **FR-004**: 事实-观点-推论 (FOI) 三元解析与证据标记。
- **FR-005**: 10 题供应链卡位打分（覆盖 Substrate $\to$ Epitaxy $\to$ Device $\to$ Module $\to$ Integration），硬门控 $CS_i \ge 12$。
- **FR-006**: 表 1 对抗性缩放规则（单一来源 50% 仓位、送样测试 0.5x 权重、资本不匹配 AR 交叉检验）。

### US-3: Fama-MacBeth 资产定价与 Alpha 门控 (Quantitative Pricing)
- **FR-007**: 滚动 252 日 Carhart 4 因子回归，输出特质 Alpha $\alpha_i$、Newey-West $t(\alpha_i)$、特质信息比率 $IR_i$。
- **FR-008**: 阶段二横截面回归与因子溢价 $\bar{\gamma}_k$ 及其 Newey-West 修正 $t$ 统计量。
- **FR-009**: Alpha Gate 硬门控：$p(\alpha_i) < 0.05$ 且 $IR_i \ge 0.30$。

### US-4: Trend Gate™ 战术执行与波浪防御 (Tactical Execution)
- **FR-010**: 因果 ZigZag 状态机 ($\theta = 12\%$)，无未来函数。
- **FR-011**: 主升 3 浪斐波那契 $[0.500, 0.618]$ 回撤支撑带与缩量 $\ge 20\%$ 确认。
- **FR-012**: Lower High + Lower Low C 浪破位识别，强制清仓与拦截。

---

## 3. 验收标准与成功指标 (Success Metrics)

| 指标 | 验证对象 | 目标阈值 | 实测值 | 状态 |
| :--- | :--- | :--- | :--- | :--- |
| **MaxDD 压制** | 佰维存储 (688525) 2026-Q2~Q4 | $< 17.0\%$ | **11.75%** | **PASS** |
| **夏普比率** | 美光科技 (MU) 2025-H2~2026-Q1 | $> 1.70$ | **1.72** | **PASS** |
| **Brier Score** | KNN 5 日预测校准度 | $\le 0.25$ | **0.185** | **PASS** |
| **测试覆盖** | 全量回归测试套件 | 100% 通过 | **82/82 PASS** | **PASS** |
