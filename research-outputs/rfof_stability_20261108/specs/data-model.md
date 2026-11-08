# 数据模型

## 实体

### PriceSeries
单只 ETF 或期货的日频收盘序列。
- 字段:`code`、`name`、`index`(`DatetimeIndex`,严格递增、无重复)、`close`(float,> 0)。
- 校验:`dates` 与 `kline` 等长;K 线顺序为 [开, 收, 低, 高],收盘取下标 1。

### AuditRecord(`etf_data_audit.csv`)
- 字段:`code,name,start,end,n_days,n_nan,n_nonpos,n_gap_gt10d,n_outlier_ret,max_abs_ret,price_cagr_pct,ann_vol_pct,max_dd_pct`。
- 规则:`n_outlier_ret` 为单日 |收益| 超过涨跌停幅度的天数;非 0 的品种不进入第一轮候选池。

### WeightSchedule
某方法在各再平衡日的目标权重。
- 字段:`method`(A0–A3)、`rebalance_date`、`code`、`weight`。
- 约束:各 `rebalance_date` 下权重 ≥ 0 且和为 1(A3 允许部分权重归现金,现金记为 `CASH`);单资产权重 ≤ 上限;生效日为 `rebalance_date` 之后的下一交易日。

### MethodResult
- 字段:`method`、`param_id`、`window`(`full` 或窗口名)、`max_dd_pct`、`ann_vol_pct`、`ann_ret_pct`、`turnover`、`cost_drag_pct`。

### FuturesVariant
- 字段:`variant`(B0–B4)、`roll_cost_bps`、`rolls_per_year`、`margin_pct`、`ma_window`、`holiday_mode`(`ffill`/`calendar`)、`ann_ret_pct`、`ann_vol_pct`、`max_dd_pct`。
- 约束:B0 必须复现 `precomputed_core_returns.csv` 中的 `r_futures_hedge`(容差 1e-9)。

### Verdict
- 字段:`method`、`c1_windows_better`(整数,0–4)、`c1_pass`、`c2_full_dd_gain_pp`、`c2_median_better`、`c2_pass`、`c3_ret_cost_pp`、`c3_pass`、`label`(`improved` / `no_significant_improvement`)。
- 规则:`label=improved` 当且仅当 c1、c2、c3 全部为真。

## 关系与状态
`PriceSeries` → `WeightSchedule`(每方法一份)→ `MethodResult`(按窗口与参数展开)→ `Verdict`(对比 A0)。`FuturesVariant` 独立于防守层,其结果作为进攻核敏感性单独报告,两者不混合。

## 验证规则
- 追加未来数据不改变历史 `WeightSchedule`(无前视测试)。
- 候选池任一 ETF 出现异常日则抛错并列出日期(坏数据路径)。
- 空窗口或窗口内样本不足 20 日时,该窗口结果标记缺失,不参与判定,且判定输出里要说明。
