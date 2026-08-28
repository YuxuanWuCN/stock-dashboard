# Feature Specification: StockDashboard v3.0 & Serenity Chokepoint 12-Week Joint Research & Production Implementation Roadmap

## 1. Executive Summary & Overview
- **Project**: StockDashboard v3.0 & Serenity Chokepoint Investing (SCI) 12-Week Joint Research & Implementation
- **Author**: Yuxuan Wu (Aberdeen Institute, South China Normal University)
- **Mentor Project**: Serenity Chokepoint Investing (SCI / yuyang-rgb094)
- **Objective**: Establish an academic-grade, production-ready quantitative research system bridging qualitative LLM hypotheses with rigorous econometric validation (Two-Stage Fama-MacBeth OLS), Network-Augmented LLM Embeddings (NALE / Yılkı 2026), Nowcasting financial reporting lag bypass, Geometric Factor Coordinate Alignment (GFCA), and tactical execution gatekeepers (Wave 4 Fibonacci & Trend Gate).

## 2. Clarifications
### Session 2026-08-26
- **Q1: Phase I 多因子定价内核扩展方案** → **A: 双轨制架构**。学术基准锁定 Carhart 4 因子（$|t| < 3.0$ Harvey et al. 2016 严苛截断），实盘策略无缝扩展为 7 因子模型（Carhart 4 + 东财微观资金流 3 因子：主力大单净流、北向增减仓、机构席位占比）。
- **Q2: Phase II 供应链图谱矩阵 $W$ 与 NALE 动态机制** → **A: 财报季动态切片稀疏矩阵 ($W_t$)**。基于上市公司定期报告披露前五大客户/供应商动态重构拓扑与权重，日频采用前向填充 CSR 稀疏矩阵，实现兼顾依赖度真实更替与毫秒级矩阵传导。
- **Q3: Phase II Week 7 Nowcasting 减值惩罚函数** → **A: 二次非对称惩罚函数**。$\text{Drift}_{\text{GFCA}} = -\lambda \cdot \left(\max\left(0, \frac{P_{\text{prepay}} - P_{\text{spot}}}{P_{\text{prepay}}}\right)\right)^2$（$\lambda = 0.5$），轻微倒挂温和扣分，深度倒挂断崖式扣减 GFCA 几何坐标，匹配半导体存货减值的非线性特征。
- **Q4: Phase III Week 9–10 Trend Gate™ 与头寸清算联动** → **A: 全量强制清仓（Emergency Liquidation）**。一旦 Trend Gate 侦测到 C 浪主跌（$G_i = 0$），执行零容忍硬风控，不仅 100% 物理拦截所有新增买单，且在次日开盘对该标的已有持仓进行 100% 市价强制清仓，坚决规避主跌浪尾部风险。
- **Q5: 终期交付工件与推送边界** → **A: 本地高标准闭环（暂不推送到老师仓库）**。交付工件聚焦在本地 `reports/thesis/`（LaTeX 学术论文）、`docs/`（60 FPS 大屏看板数据包）与 `tests/backtest_benchmark.py`（封箱回测套件），完全在本地验证通过前严禁向老师 upstream 仓库推送。



---

## 2. 12-Week Roadmap Three Core Phases

### Phase I: Econometric Kernel & Factor Decoupling (Weeks 1–4)
1. **Week 1: Unified DataOps & Multi-Market Adapter**
   - *Research*: Multi-market data mapping schema translating free-source A-share daily/weekly/monthly data (AKShare, Kenneth French Library) into standard risk factors (MKT, SMB, HML, MOM), mimicking high-cost institutional databases (Wind/CSMAR).
   - *Engineering*: Implement `src/data/adapter.py` abstraction layer, raw data loaders, alignment functions, and structured cash-flow indicators.
2. **Week 2: Fama-MacBeth Stage 1 Regression (Time-Series)**
   - *Research*: Rolling-window OLS to estimate individual asset risk exposures ($\beta_{i,k}$) against Carhart 4-factor baseline model.
   - *Engineering*: Develop Stage 1 OLS regression kernel in `famamacbethv3.py`, handle collinearity controls (VIF), compute rolling factor loadings, export dynamic covariance matrices.
3. **Week 3: Fama-MacBeth Stage 2 Regression (Cross-Sectional) & HAC Adjustments**
   - *Research*: Cross-sectional regressions to estimate risk premiums ($\gamma_t$) and isolate idiosyncratic excess returns (Alpha). Introduce Newey-West HAC covariance adjustments.
   - *Engineering*: Implement cross-sectional OLS with Newey-West correction. Automated factor prune gate: factors with $|t| < 3.0$ (Harvey et al., 2016) programmatically suppressed.
4. **Week 4: Geometric Factor Coordinate Alignment (GFCA)**
   - *Research*: Map multi-dimensional factor scores into standardized $K$-dimensional space $[-1, 1]^K$ via smooth hyperbolic tangent ($\tanh$) filter.
   - *Engineering*: Implement `align_gfca_coordinates` in `scoringv3.py`, cross-sectional normalization, and spatial visualization maps.

### Phase II: Supply Chain Graph Propagation & Nowcasting (Weeks 5–8)
5. **Week 5: Supply Chain Knowledge Graph (KG) & Adjacency Matrix**
   - *Research*: Data extraction protocols for supplier-customer linkages in China A-shares (LLM RAG extraction vs structured relational databases).
   - *Engineering*: Develop `SupplyChainGraph` class, formulate directed economic adjacency matrix $W$ with edge weights $w_{ji}$ scaled by procurement ratios, prepayment percentages, revenue dependency.
6. **Week 6: Network-Augmented LLM Embeddings (NALE) Implementation**
   - *Research*: Adapt Yılkı (2026) NALE algorithm for upstream-to-downstream transmission of non-structural textual signals with propagation weight $\alpha = 0.4$.
   - *Engineering*: Implement `calculate_nale_score` in `scoringv3.py`. Build Placebo verification suite shuffling edge connections 100 times.
7. **Week 7: Nowcasting & Multi-Source Triangle Validation**
   - *Research*: Evidence Triangulation mechanism (BIWIN Storage case study) using leading indicators (Korea Customs export stats, DRAM/NAND spot prices, downstream prepayments) to bypass 1-3 month reporting lag.
   - *Engineering*: Integrate Nowcasting ingestion channel and Impairment Penalty rule.
8. **Week 8: FinRobot-Based Unified Pipeline Runner (Issue #4 PR)**
   - *Research*: DAG state machine for end-to-end pipeline orchestration.
   - *Engineering*: Build pipeline scheduler in Serenity repository with thread-safe `SessionState` context packet, prepare comprehensive PR for master project.

### Phase III: Tactical Execution Gatekeepers & Bet Sizing (Weeks 9–12)
9. **Week 9: Trend Gate Boolean Gatekeepers**
   - *Research*: Trend-filtering math logic combining MA20, MACD histogram momentum, and Elliott Wave C-wave detection.
   - *Engineering*: Implement `TrendGate` class in `trend_gate.py` with binary gatekeeper $G_i \in \{0, 1\}$.
10. **Week 10: Differential Position Sizing & Bet Types**
    - *Research*: Risk-budgeting allocation strategies under Catalyst Alpha, Super Beta, Event-Driven across evidence phases (Sampling, Batching, Mass Production).
    - *Engineering*: Implement `DynamicBetAllocator` in `portfolio.py`.
11. **Week 11: Sealed-Box Benchmarking & Backtesting**
    - *Research*: Sample out-of-sample (OOS) testing framework (Sharpe, IR, Max Drawdown) on key holdings (001258, Micron MU).
    - *Engineering*: Write `tests/backtest_benchmark.py` simulation suite and export NAV curves.
12. **Week 12: Thesis Compilation & Project Delivery**
    - *Research*: Academic thesis compilation (formal quantitative paper format).
    - *Engineering*: Code audits, 60 FPS dashboard rendering optimization, complete Issue #4 PR merge.

---

## 3. Ambiguity & Key Design Decision Categories
- **Econ Engine**: Factor universe scope (Standard Carhart 4 vs EastMoney Micro Capital Flows 5-factor).
- **Network Graph Topology**: Static graph vs Dynamic time-varying adjacency matrix $W_t$.
- **Execution & Storage**: Local SQLite vs Parquet Data Lake caching format.
- **Thesis & Deliverables**: LaTeX academic paper output directory and benchmark matrix validation standards.
