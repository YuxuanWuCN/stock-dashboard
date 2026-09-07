# 实现计划：300 支股票全池 Fama-MacBeth 深度两阶段回归与学术研讨规划

**分支**：`contest-2026` | **日期**：2026-09-07 | **规格**：[spec.md](spec.md)  
**设计模板**：遵循 `.specify/templates/plan-template.md` 与国创科研标准

---

## 1. 概要 (Summary)

构建并执行 300 支股票全池因果回归流水线。利用 2024-2026 年（694 交易日）跨周期数据，结合 CSMAR 官方 Carhart 四因子体系，对全部 300 支标的执行逐标的时间序列 OLS + Newey-West HAC 检验，并逐日开展横截面 Fama-MacBeth 回归。输出统计结果表格与学术实证报告，直接支持队长组织团队进行深入的因子回归研讨会。

---

## 2. 技术背景与设计选择 (Technical Context)

- **核心语言与环境**：Python 3.13 + statsmodels 0.14.4 + scipy 1.15.2 + pandas 2.2.3。
- **协方差修正**：采用自适应 Newey-West 滞后阶数 $q = \lfloor 4 \times (T/100)^{2/9} \rfloor$（在 $T=694$ 时自动选取 $q=6$），确保异方差与自相关条件下的置信区间与 p 值绝对稳健。
- **产业聚类集成**：打通 `data/task_split/`，将回归结果映射到三位数据层同学（每人 100 支标的）的认领范围。

---

## 3. 章程与门禁检查 (Constitution Check)

- [x] **数据真实性与不可伪造**：严格基于 694 交易日行情与因子序列计算，绝不捏造 p 值与 t 统计量。
- [x] **单标的独立隔离**：逐标的计算收益率与残差，不存在跨标的污染。
- [x] **测试与复现性**：一键运行 `python scripts/run_300stocks_deep_regression.py` 即可在本地 10 秒内完整复现所有统计指标与报告。

---

## 4. 实施阶段与架构安排

### 阶段 0: 数据与因子矩阵准备
- 验证 `data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv` 与 `factors.csv`。
- 读取 `data/task_split/universe_300_assigned.csv` 完成代码补零与组员产业归类。

### 阶段 1: 算法核心与脚本构建 (`scripts/run_300stocks_deep_regression.py`)
- 实现 `calc_newey_west_lags()` 自适应滞后阶数。
- 实现 `run_stage1_time_series()`：计算 300 支标的 $\alpha, \beta, p, IR, R^2$。
- 实现 `run_stage2_fama_macbeth()`：计算每日 $\lambda_{k, t}$ 与 Fama-MacBeth 统计量。
- 实现 `compute_cohort_breakdown()`：生成三位同学板块的对比指标。

### 阶段 2: 产物落地与交付
- 导出 `reports/tables/regression_300stocks/stage1_stock_alphas.csv`
- 导出 `reports/tables/regression_300stocks/stage2_factor_premia.csv`
- 导出 `reports/tables/regression_300stocks/cohort_regression_summary.csv`
- 生成发布级学术实证报告 `reports/tables/regression_300stocks/fama_macbeth_regression_report.md`
