# Feature Specification: 300 支股票全池 Fama-MacBeth 深度两阶段回归与学术检验

**Feature Branch**: `contest-2026`  
**Created**: 2026-09-07  
**Status**: Completed & Ready for Team Review  

---

## 1. 目标与背景 (Objective & Background)

针对国创项目 300 支核心股票池（涵盖硬科技半导体、绿电清洁能源、黄金周期资源、大金融银行券商、大消费与医药生物、高端装备工业 6 大核心板块），在 2024-2026 全周期（694 交易日）下执行深度**Fama-MacBeth 两阶段资产定价回归**：

1. **解决核心痛点**：防止团队把“单纯行情好（高 Beta）”当成算法的“选股超额收益（Alpha）”。
2. **多因子剥离**：严格剥离市场 (`MKT`)、规模 (`SMB`)、价值 (`HML`)、动量 (`MOM`) 风格暴露，提炼出真正具有超额收益且统计显著的特质 Alpha。
3. **赋能数据层分工**：将回归结果与分派给三位数据层同学的各 100 支标的深度绑定，提供科学的产业对照结论。

---

## 2. 用户场景与验收标准 (User Scenarios & Acceptance)

### User Story 1 - 阶段一时间序列回归与 Alpha 纯度检验 (P1)
- **输入**：300 支标的日频超额收益率矩阵 + Carhart 4 因子序列 + 无风险利率。
- **算法**：OLS 时间序列回归，采用自适应 Newey-West HAC 稳健标准误（消除自相关与异方差）。
- **验收标准**：
  - 产出每只股票的年化 Alpha、t 统计量、p 值、信息比率 $IR = \frac{\alpha}{\sigma(\epsilon)}$。
  - 判定准则：若 $p < 0.05$ 且 $IR \ge 0.30$，分类为 `True Alpha`；若 $p \ge 0.05$ 且 $\beta_{mkt} > 0.5$，分类为 `Pure Beta`。

### User Story 2 - 阶段二横截面回归与因子风险溢价检验 (P1)
- **输入**：阶段一估计得到的 300 支股票 Beta 载荷矩阵。
- **算法**：逐日运行横截面 OLS 回归求出每日溢价 $\lambda_{k, t}$，随后时间序列求均值并计算 Fama-MacBeth 统计量 $t = \frac{\bar{\lambda}_k}{\sigma(\lambda_k)/\sqrt{T}}$。
- **验收标准**：
  - 输出各因子的年化风险溢价、标准误、t 统计量与显著性。

### User Story 3 - 三大组员产业组别对比分析 (P1)
- **输入**：`data/task_split/universe_300_assigned.csv` 分组映射。
- **验收标准**：
  - 统计同学 A（硬科技与制造）、同学 B（绿电与周期）、同学 C（金融与消费医药）的平均 Alpha、平均 IR、平均 Beta、True Alpha 占比。
  - 生成学术报告并提供可操作的组员讨论指引。
