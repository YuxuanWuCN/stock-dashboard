# 函数级契约 —— 熊市压力测试

本功能无 HTTP API；契约以 Python 函数签名 + 不变量形式定义。
所有契约由 `tests/test_portfolio_stress.py`（33 项）逐条锁定。

## C1. `identify_bear_windows(nav_series, dd_threshold=0.15, min_duration=20, pre_pad=20, post_pad=20, rapid_drop_threshold=-0.08, rapid_drop_window=5) -> List[BearWindow]`

- 输入：日期升序净值 Series；输出窗口按时间升序。
- **不变量**：窗口互不重叠（含 padding 后）；`bear` 类 duration ≥ min_duration；退出判定使用"从谷值回缩后 DD < threshold×0.5"。
- 边界：13 个月真实数据返回 `[]` 是合法结果，调用方必须如实报告"数据不足"，不得放宽阈值凑窗口。

## C2. `apply_price_shock(returns_df, scenario, risk_asset_cols, defensive_cols, defensive_mode="defensive_plus2pct") -> pd.DataFrame`

- **不变量 1**：返回新对象，输入 DataFrame 逐位不变（`test_original_df_unchanged`）。
- **不变量 2**：冲击超出数据长度时自动截断，不抛错（`test_shock_truncated_by_window`）。
- 风险资产列前 `duration_days` 行收益被覆盖为冲击收益；防御列按 defensive_mode 覆盖。

## C3. `apply_correlation_stress(returns_df, satellite_cols, target_corr=0.8, n_days=20) -> pd.DataFrame`

- 前 n_days 行通过"共同分量混合"把卫星列间相关性推向 target_corr；列数 < 2 时原样返回副本。

## C4. `apply_liquidity_to_weights(current_weights, target_weights, scenario, nav) -> (executed_weights, turnover, cost)`

- `turnover = 0.5·Σ|Δw_executed|`；`cost = turnover · one_side_cost_bps/1e4`（单边口径）。
- **不变量**：`Σ executed_weights = 1`；fill_fraction<1 时未成交部分保留原仓（0.6→0.3 目标半成交 = 0.45，不是 0.3 也不是 0）；换手上限命中时 turnover ≤ max_daily_turnover；无变化时 turnover=cost=0。

## C5. `RebalanceManager.apply_deadband_and_execute(date, current_weights, target_pw, fill_fraction=1.0) -> (...)`

- `fill_fraction=1.0`（默认）返回值与不传该参数**完全相等**（向后兼容锁 `test_fill_fraction_one_is_backward_compatible`）。
- `0 < fill_fraction < 1`：在死区/换手裁剪**之后**按 `w_c + (w_e − w_c)·fill_fraction` 部分成交，重新计算 turnover。

## C6. `FOFBacktestEngine.run_backtest(mode, signals_by_date, config, t_nale_halflife=5.0, t_nale_age_map=None, fill_fraction=1.0, delayed_exit_days=0, frozen_exit_days=0)`

- mode ∈ STRESS_MODES；未知 mode 抛 ValueError。
- **日期键契约**：`returns_df.index` 允许 str 或 Timestamp；引擎内部 `_norm_date` 归一化为 "YYYY-MM-DD" 后查 `signals_by_date`（修复历史隐藏 bug：Timestamp 导致信号永远查不到）。
- **t_nale 衰减**：`score' = score · 0.5^(age/halflife)`；age=halflife → 0.5×score；age=0 → 原 score。
- **严重度跳变语义**：升级（curr≥defensive 且 > prev）在当日收盘后判定；`frozen` 窗口 = [i+1, i+frozen_exit_days]，窗口内风险资产（beta+卫星合计）净减仓被拦为 0 换手 0 费用；`delayed` 强制减仓在 i+delayed_exit_days+1 日以触发状态覆盖目标（仅当能降低风险敞口时）。
- **不变量**：默认参数组合（fill=1.0, delayed=0, frozen=0）结果与参数引入前一致（`test_defaults_reproduce_unchanged_behavior`）。

## C7. `ParamGrid.one_factor_at_a_time() -> List[Dict]` / `total_combinations() -> int`

- OFAT 每变体仅一个维度偏离基准并带 `_dimension` 标签；总数 24；全组合 > 1000（用于论证 OFAT 必要性）。
- **纪律条款**：网格值在构造时冻结（frozen dataclass 默认字段），实验后不得追加/修改取值挑赢家。

## C8. 产物契约（`reports/fof_stress_20261014/`）

| 文件 | 必须列/内容 |
|---|---|
| historical_results.csv | 每模式一行：mode + PerformanceMetrics 全字段（禁止把日志对象序列化进单元格） |
| synthetic_shock_results.csv | scenario × defensive_mode × mode，153 行 |
| liquidity_results.csv | 9 情景 × (cost_bps, fill_fraction, delayed, frozen, turnover_cap, max_drawdown, total_cost, sharpe)，**除成本维度外各情景结果必须可区分** |
| parameter_sensitivity.csv | 24 个 OFAT 变体 |
| bear_stress_report.md | §1 历史窗口 §2 历史对照 §3 合成冲击 §4 执行压力 §5 结论；历史/合成/执行三类分开表述 |
