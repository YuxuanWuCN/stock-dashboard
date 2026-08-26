# Implementation Plan: 2025Q2–2026Q7 存储市场物理隔离样本外量化回测

## 1. 物理隔离数据架构与设计

```mermaid
graph TD
    subgraph Raw["1. 原始只读数据区 (data/raw/backtest_storage_2025q2_2026q7/)"]
        D1["2025Q2-2026Q7 存储标的日K行情 (001309, 300475, 301308, 688525, 688008, MU)"]
        D2["宏中观现货与海关数据 (DXI Index, Korea Customs YoY)"]
        D3["多因子数据 (Carhart 4 + 东财微观资金流 3 因子)"]
    end

    subgraph Engine["2. 拟真交易人逐步推进引擎 (src/analysis/storage_backtest_runner.py)"]
        E1["时点 t: 仅读取 <= t 历史数据 (No-Lookahead)"]
        E2["Fama-MacBeth Stage 1 & 2 -> 剥离特异 Alpha"]
        E3["NALE 图谱传导 (W_t, α=0.4) + Nowcasting 二次减值惩罚"]
        E4["GFCA 空间对齐 -> Trend Gate™ (MA20+MACD+C浪清仓)"]
        E5["DynamicBetAllocator 计算头寸 -> t+1 开盘撮合 (0.125%/0.175% 摩擦)"]
        E1 --> E2 --> E3 --> E4 --> E5
    end

    subgraph Outputs["3. 物理隔离输出工件与报告"]
        O1["reports/figures/ (>=200 DPI 净值曲线、水下回撤、GFCA散点)"]
        O2["reports/tables/ (Sharpe, Calmar, MaxDD, IR 对照表格)"]
        O3["docs/data/paper/ (前端大屏交互数据包)"]
    end

    Raw --> Engine --> Outputs
```

---

## 2. 三级对照组评估标准与实证假设

- **策略组 (Active Strategy)**: GFCA + NALE + Nowcasting 减值惩罚 + Trend Gate™ C 浪紧急清仓 + DynamicBetAllocator。
- **对照组 1 (宽基基准)**: 沪深 300 指数 (`000300.SH`)。
- **对照组 2 (行业基准)**: 半导体芯片 ETF (`512760.SH`)。
- **对照组 3 (板块买入持有)**: 存储 5 巨头等权买入持有 (`Storage_EW_BuyHold`)。

**预期实证假设**:
1. **2025Q2–2025Q4 顺周期阶段**: 策略组由于 NALE 供应链正向增强与 Catalyst Alpha 集中配置，弹性跑赢芯片 ETF 与沪深 300；
2. **2026Q1–2026Q7 均值回归与回调阶段**: 存储板块发生 C 浪深跌，`Storage_EW_BuyHold` 发生大幅利润回吐（最大回撤 $>30\%$）；而策略组凭借 **Trend Gate™ ($G_i=0$) 与 Nowcasting 二次减值惩罚** 在高位果断清仓空仓，将最大回撤严格压制在 $15\%$ 以内，最终实现远超买入持有的 Information Ratio 与最终收益率！
