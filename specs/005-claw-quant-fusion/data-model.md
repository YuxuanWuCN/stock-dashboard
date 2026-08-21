# Data Model: 领先信号 / 因子质量 / 信念执行 / 约束（005 融合）

## 1. LeadingSignal（领先指标快照，docs/data/leading_signals/{category}.json）

| 字段 | 类型 | 说明 |
|---|---|---|
| category | str | semiconductor / optical_communication / new_energy / gold_resources |
| industry_name | str | 行业中文名 |
| description | str | 数据源语义描述 |
| proxy_type | str | 代理类型（customs_and_spot_price 等） |
| keywords | list[str] | 关键词 |
| data_source | str | "akshare" | "synthetic_fallback" |
| source_name | str | 具体源名（"半导体行业指数（领先代理）"） |
| series | list[float] | 真实价格序列（仅 akshare 时存在） |
| momentum_metrics | dict | slope_pct / momentum / inflection_flag / latest_value / confidence |
| updated_at | str | 抓取时间 |

## 2. Composite 扩展（scoring.py 输出）

| 字段 | 说明 |
|---|---|
| leading | float 0-100（50 中性；拐点 ±30） |
| leading_reason | str | None（拐点/动能理由） |

## 3. FactorQuality（docs/data/factors/quality_report.json 扩展）

| 字段 | 说明 |
|---|---|
| factors.{F}.half_life_days | int | None（自相关 IC 衰减到峰值一半的天数） |
| factors.{F}.note | 样本不足/未衰减标注 |
| crowding.level | crowded / moderately_crowded / uncrowded / unknown |
| crowding.avg_corr | 两两相关均值绝对值 |
| crowding.hhi | 方差集中度 |

## 4. Thesis / Holdings（信念-执行分离）

| 实体 | 字段 |
|---|---|
| Thesis | code/name/core_logic/expectation_gap/invalidation_conditions/status(valid|invalid)/history |
| Holdings | code/weight/quantity/avg_cost/last_price/last_rebalance/market_value/unrealized_pnl_pct |

## 5. PortfolioConstraints（7 类约束）

| 约束 | 默认值 |
|---|---|
| max_single_position | 0.20 |
| max_industry_concentration | 0.40 |
| max_monthly_turnover | 0.30 |
| min_daily_liquidity | 0.0（不强制） |
| max_market_cap_billions | 0.0（不强制） |
| max_valuation_percentile | 1.0（不强制） |
| min/max_cash_ratio | 0.05 / 0.95 |
