# Implementation Plan: 60日202支股票全池物理隔离量化回测与每周冠军演化系统

## 1. 架构流转图

```mermaid
graph TD
    subgraph RawData["1. 物理隔离原始数据 (data/raw/backtest_paper_60d_202stocks/)"]
        R1["202 支股票 60 交易日真实行情 (market_prices.csv)"]
        R2["多因子与资金流矩阵 (factors.csv)"]
        R3["宏观市场温度序列 (market_temperature.csv)"]
    end

    subgraph SimulationEngine["2. 拟真交易人与每周冠军演化引擎 (src/pipeline/paper_60d_evolution_runner.py)"]
        E1["每日决策: GFCA 多因子打分 + Trend Gate 过滤 + 大盘温度仓位门控"]
        E2["日频交易: 撮合撮单 (买0.125%/卖0.175%) + 单股 -8% 强制止损"]
        E3["六大主力组合跟踪 (激进/稳健/防守/科技/蓝筹/全球) 及派生变体"]
        E4["每周五复盘: 周度夏普/卡玛综合评选 -> 选出周冠军 (Weekly Champion)"]
        E5["基因派生变体: 参数自适应变异生成下一代变体并记录演化树"]
        E1 --> E2 --> E3 --> E4 --> E5
    end

    subgraph AccuracyEval["3. 四维量化正确率与预测校准评定"]
        A1["方向预测正确率 (Directional Hit Rate vs 70% 基线)"]
        A2["实盘交易胜率 (Trade Win Rate) 与 盈亏比 (Profit/Loss Ratio)"]
        A3["Brier 概率校准度与 Harvey |t|>=3.0 显著性"]
    end

    subgraph SystemSync["4. 全系统工件与前端 HTML 看板更新"]
        S1["reports/tables/accuracy_and_performance_report.md"]
        S2["reports/figures/ (全组合净值图, 水下回撤图, 策略进化树图)"]
        S3["docs/data/paper/ 与 docs/data/quantitative/ (全量更新)"]
        S4["docs/portfolio.html 与 docs/index.html (前端大屏联动)"]
    end

    RawData --> SimulationEngine
    SimulationEngine --> AccuracyEval
    SimulationEngine --> SystemSync
```

---

## 2. 六大组合与变体演化矩阵

| 组合名称 | 风险偏好 | 选股策略特征 | 基础仓位上限 |
| :--- | :--- | :--- | :---: |
| **激进成长 (`portfolio_aggressive`)** | 高弹性 (Aggressive) | GFCA 高动量 + NALE 高弹性 + 题材催化 | 95% |
| **均衡稳健 (`portfolio_robust`)** | 均衡 (Robust) | GFCA 综合分均衡 + 行业分散 + 均线多头 | 80% |
| **防御保守 (`portfolio_defensive`)** | 低风险 (Defensive) | 高股息/大盘蓝筹/黄金ETF/低波动 | 60% |
| **科技主题 (`portfolio_tech`)** | 行业聚焦 (Tech) | 半导体芯片/算力/CXL/存储/AI产业链 | 90% |
| **蓝筹价值 (`portfolio_bluechip`)** | 核心资产 (Bluechip) | 沪深300/中字头/金融消费龙头 | 75% |
| **全球配置 (`portfolio_global`)** | 跨境对冲 (Global) | 纳指ETF/标普ETF/德国ETF/黄金/跨境QDII | 80% |

---

## 3. 正确率评估标准 (对比老版本 70% 纯大模型基线)

1. **方向预测正确率**: $\text{HitRate} = \frac{\sum \mathbb{I}(\text{Sign}(\text{Pred}) == \text{Sign}(\text{Actual}))}{N_{samples}}$；
2. **实盘调仓胜率**: 扣除买卖摩擦后盈利交易笔数占比；
3. **盈亏比**: $\frac{\text{平均盈利幅度}}{\text{平均亏损幅度}}$；
4. **回撤控制**: 单股 $-8\%$ 硬止损与 Trend Gate $G_i=0$ 阻断下的最大回撤。
