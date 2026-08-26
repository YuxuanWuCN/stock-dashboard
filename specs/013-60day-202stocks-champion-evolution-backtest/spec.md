# Feature Specification: 60日202支股票全池物理隔离量化回测与每周冠军演化系统

## 1. 目标与范围 (Objective & Scope)
- **目标**: 运用全新的 12 周量化多维引擎（Fama-MacBeth 双阶段回归 + GFCA 几何空间对齐 + NALE 供应链传导 + Nowcasting 二次减值惩罚 + Trend Gate™ 战术门禁 + DynamicBetAllocator 阶梯控仓），对全池 **202 支 A 股与 ETF 标的** 执行为期 **60 个交易日** 的物理隔离日频拟真回测。
- **核心业务逻辑**:
  1. **每日动态择票与调仓 (Daily Stock Selection & Rebalance)**：日频多因子评分、大盘温度仓位门控、Trend Gate 趋势过滤与单股 -8% 严格硬止损。
  2. **每周冠军派生与策略进化 (Weekly Champion Derivation & Mutation)**：横跨六大主力组合（激进成长、稳健均衡、防御保守、科技主题、蓝筹价值、全球配置）及其变体（v1/v2/v3、动量加权、Top5精选），每周复盘评选出“周度冠军策略”并生成派生变体。
  3. **系统正确率与预测命中率评估 (Accuracy, Hit Rate & Calibration)**：统计多因子得分对次日/5日/20日收益方向预测的命中率（与此前 70% 纯大模型基线做科学对比）、盈亏比、夏普比率与最大回撤。
  4. **全系统与前端 HTML 看板更新**：全量更新 `docs/data/paper/`、`docs/data/quantitative/` 与 `docs/portfolio.html`、`docs/index.html`。

---

## 2. 物理数据隔离契约 (Physical Data Isolation Contract)
- **原始只读区**: `data/raw/backtest_paper_60d_202 stocks/`，存储 202 支标的的 60 天完整行情与因子底表。
- **派生处理区**: `data/processed/backtest_paper_60d_202stocks/`，存储日频截面快照、图谱矩阵与每周派生数据。
- **图表与表格工件**: `reports/figures/backtest_paper_60d_202stocks/` 与 `reports/tables/backtest_paper_60d_202stocks/`。
- **前端实时同步区**: `docs/data/paper/` 与 `docs/data/quantitative/`。

---

## 3. 澄清记录 (Clarifications)
### Session 2026-08-26
- **Q1: 202 支股票全池与 60 交易日区间** → **A: 138 现存自选 + 行业龙头/ETF 扩充至 202 支标的**。回测区间锚定为最近 60 个完整交易日（2026-06-01 至 2026-08-26），覆盖全部主流行业并与现有看板无缝续接。
- **Q2: 每周冠军评选与策略派生机制** → **A: 周度夏普/卡玛综合评选 + 优良参数基因派生 (Weekly Risk-Adjusted Champion & Mutation)**。按周度风险调整收益评选周冠军，继承优秀基因生成下一代变体，并输出策略进化树。
- **Q3: 正确率与预测命中率度量** → **A: 四维量化正确率矩阵 (4-Dimensional Accuracy Matrix)**。方向预测正确率 + 交易胜率 + 真实盈亏比 + Brier 概率校准度，全方位对比老版本 70% 纯大模型基线。



