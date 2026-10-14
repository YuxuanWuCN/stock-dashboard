# Phase 0 Research —— 熊市回测与压力测试

日期: 2026-10-14 | 来源方案: `工作规划/熊市回测与压力测试方案_交主Agent.md`

## R1. 数据覆盖

- 本地 ETF K 线：`docs/data/kline/{code}.json`（dates + kline[i][1] 收盘价），覆盖约 **2025-09-08 → 2026-08-27**（约 13 个月）。
- **结论：真实数据不足以识别满足 DD≥15% 且 ≥20 交易日的独立熊市窗口**。`identify_bear_windows` 在 510300 净值上返回 0 个窗口，报告如实说明，不伪造历史窗口。
- 历史对照退化为"全样本内下跌段"回测（2025-09 至 2026-08），并在报告中标注"不构成跨周期历史实证"。

## R2. T-NALE 现状

- 引擎原只有 4 组对照（baseline/nale/risk_constrained_nale/sentiment_only），无 t_nale、defensive_only。
- 方案要求补充：**T-NALE 时效衰减**（score × 0.5^(age/halflife)，异质半衰期）与 **defensive_only**（100% 防御底仓对照组）。
- 已实现于 `FOFBacktestEngine.run_backtest`，`STRESS_MODES` 扩展为 6 组 + benchmark_510300 共 7 列。

## R3. 引擎缺口（实施前 → 实施后）

| 缺口 | 风险 | 实施结果 |
|---|---|---|
| 流动性压力参数只有 cost_bps 生效，half-fill/delayed/frozen/turnover-cap 均为假接线 | 9 情景除成本外结果全同，压力测试形同虚设 | `RebalanceManager.apply_deadband_and_execute(fill_fraction=)` + `run_backtest(fill_fraction, delayed_exit_days, frozen_exit_days)` + `RebalanceConfig.max_single_day_turnover` 真接 |
| `returns_df.index` 为 Timestamp 时 `str(ts)`="…00:00:00" 与 signals_by_date 键（"YYYY-MM-DD"）错位 | 卫星信号永远查不到、所有依赖信号的模式静默退化（隐藏 bug） | `_norm_date()` 统一取前 10 位 |
| 未成交风险仓处理语义 | 若清零/变现金会虚增防御效果 | 半成交未成交部分**保留原仓位**（0.6→0.3 目标半成交实际 0.45） |
| 同名测试文件 `tests/sector_rotation/test_backtest_engine.py` 与 `tests/test_backtest_engine.py` 冲突 | heavy 裸 `pytest -q` 全量回归被 import file mismatch 打断 | git mv → `test_sector_rotation_backtest_engine.py` |

## R4. 既有可复用件

- `RiskBudgetManager`：回撤状态机（WATCH 5% / DEFENSIVE 8% / PROTECTIVE 10%，恢复需 3 日确认）直接复用。
- `FOFAllocator`：卫星预算分层压缩（NORMAL 0.20→WATCH 60%→DEFENSIVE 20%→PROTECTIVE 0）直接复用。
- `RebalanceConfig.max_single_day_turnover`：现成字段，turnover-cap 情景零新代码接入。

## R5. 三类实验必须分开（方案硬约束）

1. **历史回测**（真实数据，样本内）→ `historical_results.csv`
2. **合成冲击**（7 冲击 × 3 防御假设 × 7 模式 + 相关性失效）→ `synthetic_shock_results.csv`，报告中不得写成历史实证。
3. **执行压力**（成本/半成交/延迟/冻结/换手上限）→ `liquidity_results.csv`
