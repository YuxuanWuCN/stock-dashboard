# Task Breakdown: StockDashboard v3.0 & Serenity Chokepoint 12-Week Roadmap

## Phase I: Econometric Kernel & Factor Decoupling (Weeks 1–4)

- [x] **Task 1.1 (Week 1)**: 构建 `src/data/adapter.py` 统一多市场数据适配层
  - 接入 AKShare (A股) + Kenneth French (美股) + 东财妙想微观资金流。
  - 标准化输出列：`date, MKT, SMB, HML, MOM, rf, LARGE_ORDER_INFLOW, NORTHBOUND_DELTA, INST_SEAT_RATIO`。
  - 单元测试：`tests/test_data_adapter.py`。
- [x] **Task 1.2 (Week 2)**: 研发 `src/analysis/famamacbethv3.py` 时序回归 Stage 1 内核
  - 滚动窗口 OLS 估计单资产风险暴露 $\beta_{i,k}$。
  - VIF 方差膨胀因子多重共线性诊断，导出动态协方差矩阵。
  - 单元测试：`tests/test_famamacbeth_stage1.py`。
- [x] **Task 1.3 (Week 3)**: 研发 Stage 2 截面回归与 Harvey et al. (2016) $|t| < 3.0$ 修剪门禁
  - Newey-West HAC 协方差自适应修正，分离特异性 Alpha。
  - 自动因子修剪门禁：$|t| < 3.0$ 因子程序化抑制。
  - 单元测试：`tests/test_famamacbeth_stage2.py`。
- [x] **Task 1.4 (Week 4)**: 实现 `scoringv3.py` 的 GFCA 几何因子坐标对齐
  - 平滑双曲正切 ($\tanh$) 过滤函数，将多维因子映射至 $[-1, 1]^K$ 空间。
  - 生成截面空间散点坐标与可视化映射。
  - 单元测试：`tests/test_gfca_scoring.py`。

---

## Phase II: Supply Chain Graph Propagation & Nowcasting (Weeks 5–8)

- [x] **Task 2.1 (Week 5)**: 构建 `src/graph/supply_chain_graph.py` 供应链知识图谱
  - 定期报告前五大客户/供应商提取与图结构重构。
  - 生成有向经济邻接矩阵 $W_t$（按采购/预付款/营收依赖度加权），采用 CSR 动态稀疏存储。
  - 单元测试：`tests/test_supply_chain_graph.py`。
- [x] **Task 2.2 (Week 6)**: 实现 Yılkı (2026) NALE (Network-Augmented LLM Embeddings) 算法
  - 非结构化研报/调研纪要文本嵌入沿供应链上下游传导（$\alpha = 0.4$）。
  - 研发 100 次边连接随机洗牌 Placebo 蒙特卡洛检验套件。
  - 单元测试：`tests/test_nale_propagation.py`。
- [x] **Task 2.3 (Week 7)**: 研发 Nowcasting 高频证据三角互证与二次减值惩罚
  - 韩国海关半导体出口额 + InSpectrum/TrendForce DXI 现货价接入通道。
  - 二次非对称减值惩罚函数：$\text{Drift}_{\text{GFCA}} = -0.5 \times (\max(0, \frac{P_{prepay} - P_{spot}}{P_{prepay}}))^2$。
  - 单元测试：`tests/test_nowcasting_triangle.py`。
- [x] **Task 2.4 (Week 8)**: 构建基于 DAG 状态机的统一全流程调度器
  - 线程安全 `SessionState` 上下文编排。
  - 端到端打通 Phase 1 研报事实提取 $\to$ Phase 2 因子计量去噪 $\to$ Phase 3 择时执行。
  - 单元测试：`tests/test_unified_pipeline_runner.py`。

---

## Phase III: Tactical Execution Gatekeepers & Bet Sizing (Weeks 9–12)

- [x] **Task 3.1 (Week 9)**: 研发 `src/execution/trend_gate.py` Trend Gate™ 布尔门禁
  - MA20 + MACD 柱状图动量 + 艾略特波浪 C 浪侦测。
  - 快速布尔门禁 $G_i \in \{0, 1\}$：$G_i = 0$ 触发全量物理拦截与次日强制清仓。
  - 单元测试：`tests/test_trend_gate.py`。
- [x] **Task 3.2 (Week 10)**: 研发 `src/execution/portfolio_allocator.py` 差异化头寸分配器
  - `DynamicBetAllocator`：Catalyst Alpha（高频战术）、Super Beta（基准跟踪）、Event-Driven（样品 20% $\to$ 小批 50% $\to$ 量产 100% 证据阶梯）。
  - 单元测试：`tests/test_bet_allocator.py`。
- [x] **Task 3.3 (Week 11)**: 封箱基准回测与 001258 / Micron MU 案例对照
  - `tests/backtest_benchmark.py` 封箱回测套件：Sharpe、IR、MaxDD、Alpha 显著性检验。
  - 输出回测 NAV 曲线与 Drawdown 图表。
- [x] **Task 3.4 (Week 12)**: 学术论文编排 (`reports/thesis/`) 与 60 FPS 大屏数据交付
  - 编写 LaTeX 学术量化论文（IEEE/Elsevier 期刊格式），整理数学证明与实证表格。
  - 优化前端 60 FPS 大屏数据生成与本地回归验证。
