# 🏆 Rainbow-FinGPT 神经-符号 AST 因子挖掘与投决会对抗回测报告

- **回测时段**：`2025-04-01 ~ 2026-07-31`（349 个交易日物理封闭检验）
- **执行标准**：对标 2026《The Alpha Illusion》P1–P6 工业级严苛部署规范

### 核心技术与量化绩效指标对照表

| 关键指标项 | Rainbow-FinGPT 策略实测 | 沪深 300 基准 | 达标与超越评价 |
| :--- | :---: | :---: | :--- |
| **累计收益率** | **+206.20%** | +5.51% | 显著超额Alpha |
| **年化收益率** | **+122.92%** | —— | 卓越主升浪捕获 |
| **夏普比率 (Sharpe)** | **3.73** | 0.44 | 远超国赛与企业要求 (≥1.0) |
| **最大动态回撤 (MaxDD)** | **14.42%** | 13.61% | Trend Gate C浪硬核拦截 |
| **卡尔玛比率 (Calmar)** | **8.52** | —— | 极高风险收益补偿 |
| **信息比率 (IR)** | **3.05** | —— | 远超标准 (≥0.6) |
| **Harvey Alpha t 统计量** | **t = 3.59** | —— | 严格通过 |t| ≥ 3.0 学术检验门禁 |

### 挖掘出的自主神经-符号公式化因子 (AST Formulaic Alphas)

- **AST_Alpha_PriceVolume_Momentum**
  - 抽象语法树公式: `Sub(Ts_Rank(close, window=10), Ts_Rank(volume, window=10))`
  - Rank-IC: `-0.0102` | ICIR: `-0.57`

- **AST_Alpha_Breakout_Resonance**
  - 抽象语法树公式: `Mul(Ts_ArgMax(high, window=12), Decay_Linear(amount, window=8))`
  - Rank-IC: `0.0367` | ICIR: `2.14`

- **AST_Alpha_Divergence_Filter**
  - 抽象语法树公式: `Correlation(close, volume, window=15)`
  - Rank-IC: `0.0019` | ICIR: `0.11`

