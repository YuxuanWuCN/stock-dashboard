# Data Model —— 熊市压力测试域实体

全部实体为纯数据类，定义于 `src/portfolio/stress_scenarios.py`；
引擎侧扩展字段位于 `src/portfolio/backtest.py`（不新增实体）。

## E1. BearWindow（历史下跌窗口）

| 字段 | 类型 | 语义 | 约束 |
|---|---|---|---|
| start / peak / trough / end | str (YYYY-MM-DD) | 峰值前 pre_pad=20 交易日 → 谷值后 post_pad=20 交易日 | start ≤ peak ≤ trough ≤ end |
| peak_nav / trough_nav | float | 峰/谷净值 | peak_nav ≥ trough_nav |
| max_dd_pct | float | 峰谷跌幅（正数） | ≥ dd_threshold (默认 0.15) 或 rapid_drop 命中 |
| duration_days | int | peak→trough 交易日数 | bear 类 ≥ min_duration (默认 20) |
| window_type | str | "bear"（持续下跌）\| "rapid_drop"（5 日 ≤ -8% 闪崩） | 枚举 |
| data_file | str | 来源标识 | 可空 |

**状态转换（识别算法）**：升序净值 → 回撤 ≥ dd_threshold 进入候选 → 从谷值回缩期间才检查退出（回撤 < threshold×0.5 确认走出）→ 与已收集窗口重叠则丢弃。

## E2. ShockScenario（合成价格冲击，frozen）

| 字段 | 类型 | 语义 |
|---|---|---|
| name | str | 唯一标签（SHOCK_MATRIX 7 项：mild_drawdown / fast_crash / severe_crash / slow_bear / long_bear / gap_down / failed_rebound） |
| daily_shock_pct | float | 每日冲击收益（负=下跌） |
| duration_days | int | 冲击持续交易日（超出窗口自动截断） |
| initial_gap | float | 首日额外跳空（gap_down=-15% 用） |
| phases | Tuple[Tuple[float,int], …] | 多阶段（failed_rebound：(-5%,5)(+2%,3)(-4%,5)） |
| cumulative_impact (property) | float | 复利累计影响，全部情景必须 < 0 |

**防御假设（defensive_mode，3 种）**：`defensive_plus2pct`（防御涨 2%/覆盖）· `defensive_zero`（横盘 0）· `defensive_correlated_drop`（跟跌，相关性失效最悲观）。

## E3. LiquidityScenario（执行压力，frozen）

| 字段 | 默认 | 语义 |
|---|---|---|
| name | — | LIQUIDITY_MATRIX 9 项标签 |
| one_side_cost_bps | 5.0 | 单边成本（bp） |
| fill_fraction | 1.0 | 每次调仓只成交该比例，**未成交部分保留原仓（禁止清零/变现金）** |
| delayed_exit_days | 0 | 风险门升级后第 delayed+1 个交易日强制减仓 |
| frozen_exit_days | 0 | 升级后 i+1..i+frozen 交易日禁止风险资产（beta+卫星合计）净减仓 |
| max_daily_turnover | None | 单日换手上限（映射 RebalanceConfig.max_single_day_turnover，10/20/35%） |

## E4. ParamGrid（OFAT 敏感性，frozen）

7 维预声明网格（satellite_budget / target_vol / dd_thresholds / recovery_days / rebal_freq / halflife_mult / defensive_ret），基准值 + 每维 3-4 变体，共 24 个 OFAT 变体；`total_combinations() > 1000`（全组合爆炸，仅用于说明为何用 OFAT）。**网格一经声明禁止事后追加挑选最好结果**。

## E5. 引擎侧扩展（无新类）

- `STRESS_MODES` = baseline / nale / risk_constrained_nale / sentiment_only / **t_nale** / **defensive_only**（编排层另加 benchmark_510300）。
- `run_backtest` 新参数：`t_nale_halflife`、`t_nale_age_map`、`fill_fraction`、`delayed_exit_days`、`frozen_exit_days` —— 默认值下与旧行为逐位一致。
- 主循环新增瞬时状态：`prev_severity`、`frozen_until_idx`、`forced_exit_due_idx`、`forced_exit_state`（每次 run_backtest 独立初始化，不跨调用泄漏）。
