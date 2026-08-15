# 数据模型: LLM 情绪信号度量与数据口径修复（Phase 0）

**Feature**: 004-sentiment-signal-fix | **Date**: 2026-08-15

## 1. FeedbackSample（修订）

| 字段 | 类型 | 说明 |
|---|---|---|
| ret_3d_pct / ret_5d_pct | REAL \| null | **修订后 = 真实已实现收益**（event_date 后 3/5 交易日收盘口径）；不可算为 null |
| realized_ret_3d_pct / realized_ret_5d_pct | REAL \| null | 显式真实收益字段（与 ret_* 同值，冗余清晰化） |
| forecast_ret_5d_pct | REAL \| null | **原预测值**（KNN forecast.return_5d_pct），独立保存不再冒充实际 |
| sentiment_score / label / soft_label | 原字段 | 不变 |
| realized_available | BOOLEAN | 回填标记：真实收益是否可算 |

兼容规则：旧消费方读 ret_* 字段得到的将是修复后的真实收益；预测值从 forecast_ret_5d_pct 获取。

## 2. AlignmentSummary（修订）

| 字段 | 类型 | 说明 |
|---|---|---|
| directional_accuracy | REAL \| null | 决定性样本方向准确率（\|score\|>=0.1 且有真实收益） |
| decisive_sample_count | INTEGER | 决定性样本数 |
| no_score_sample_count | INTEGER | 无情感分样本数（审计用） |
| alignment_rate | REAL \| null | 旧字段原样保留（分母含全部样本） |

## 3. DiagnosisReport

- 根因审计：ret 来源（代码位置 + 样本证据）、分母构成分解
- 真实方向统计：正分/负分样本的上涨占比、样本数、Wilson 95% CI、与 50% 基线对比
- 结论：正相关 / 无关 / 反转（三选一，附区间与功效说明）
- 归档：reports/sentiment_signal_diagnosis.md（覆盖式）

## 不变量

- K 线 JSON 只读，绝不修改（FR-011）
- 回填幂等：连续两次运行结果文件逐字节一致（SC-005）
- 无前视：收益只用 event_date 之后的交易日数据（FR-007）