# Feature Specification: 2025Q2–2026Q7 存储市场 (Semiconductor Storage) 物理隔离样本外量化回测

## 1. 目标与背景 (Objective & Background)
- **回测区间**: 2025-04-01 至 2026-07-31 (覆盖 2025Q2 算力需求爆发、2025H2 晶圆涨价、2026H1 财报分化与高位回调全周期)。
- **标的资产宇宙 (Storage Universe)**:
  - A 股核心存储卡点标的：`001309` (德明利)、`300475` (香农芯创)、`301308` (江波龙)、`688525` (佰维存储)、`688008` (澜起科技)。
  - 全球供应链对照基准：`MU` (美光科技)、`WDC` (西部数据)、`KRX_000660` (SK海力士现货锚点)。
  - 基准指数：沪深 300 (`000300.SH`)、半导体芯片 ETF (`512760.SH`)。
- **核心验证算法体系**:
  - Phase I: 统一数据适配层 (`src/data/adapter.py`) + 双阶段 Fama-MacBeth OLS + GFCA $\tanh$ 空间坐标映射。
  - Phase II: 供应链图谱动态 CSR 稀疏矩阵 $W_t$ + Yılkı (2026) NALE 传导 ($\alpha = 0.4$) + 100 次 Placebo 拓扑检验 + Nowcasting 二次非对称减值惩罚。
  - Phase III: Trend Gate™ 布尔硬门禁 ($G_i \in \{0, 1\}$) C 浪强制清仓 + `DynamicBetAllocator` (Catalyst / Super Beta / Event-Driven 20%-50%-100% 阶梯控仓)。

---

## 2. 物理数据隔离规范 (Physical Data Isolation Contract)
- **原始只读数据区 (Immutable Raw Data)**: `data/raw/backtest_storage_2025q2_2026q7/`，严格只读，禁止运行时修改。
- **中间派生数据区 (Processed Data)**: `data/processed/backtest_storage_2025q2_2026q7/`，存放时序切片、因子截面与动态图谱。
- **独立结果工件区 (Isolated Reports)**:
  - 净值与度量数据包：`docs/data/paper/backtest_storage_2025q2_2026q7.json`
  - 学术图表：`reports/figures/backtest_storage_2025q2_2026q7/` (>=200 DPI, 中文标签，无前视偏误)
  - 因子实证与绩效表格：`reports/tables/backtest_storage_2025q2_2026q7/`
- **因果时间隔离 (Causal Time-Awareness)**:
  - 严禁全样本数据标准化与全局统计量泄漏；
  - 任何时点 $t$ 的因子均值、标准差、GFCA 坐标、NALE 传导与 Trend Gate 状态只能使用 $s \le t$ 的历史窗口数据。

---

## 3. 澄清记录 (Clarifications)
### Session 2026-08-26
- **Q1: 物理隔离回测执行模式** → **A: 日频真实拟人化因果逐步推进 (Real-World Trader Walk-Forward Simulation)**。在交易日 $t$ 收盘仅读取 $\le t$ 产生的行情与公告，动态计算 rolling 载荷、GFCA 坐标、NALE 图谱传导与 Trend Gate 门禁，并在 $t+1$ 日开盘按真实撮合价执行，物理级隔绝未来函数。
- **Q2: 交易摩擦与滑点模型** → **A: 真实 A 股机构标准费率**。买入综合成本 0.125%（佣金 0.25‰ + 滑点 1.0‰），卖出综合成本 0.175%（佣金 0.25‰ + 滑点 1.0‰ + 印花税 0.5‰），闲置现金按年化 1.8%（日化 0.005%）计息。
- **Q3: 对照组评估体系** → **A: 三级科学对照组基准矩阵 (3-Tier Benchmark Matrix)**。包含沪深300、半导体芯片ETF及存储5巨头等权买入持有策略，精准分离行业系统性 Beta 与量化择时 Alpha。
- **Q4: 图表工件与前端大屏同步** → **A: 出版级图表矩阵 + HTML 前端看板数据同步**。输出 $\ge 200\text{ DPI}$ 中文高清净值图、水下回撤图、GFCA空间散点图与 Markdown 表格，并同步更新 `docs/data/paper/` 前端 JSON 数据包供看板交互展示。




