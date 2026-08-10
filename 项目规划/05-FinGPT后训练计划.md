# FinGPT 特殊后训练计划（RLHF 风格：用真实市场反馈校准参数）

> 约定记录：2026-08-10 与用户确认。用户明确要求：FinGPT 管线必须经历
> 「跑 → 真实对决 → 反馈 → 调参」的后训练闭环，激进模拟盘对决为此提供样本。

## 1. 背景

FinGPT 的设计本来就包含 RLHF/后训练环节：用市场反馈（预测 vs 实际）
反向校准模型。本项目无法直接改 DeepSeek API 权重，因此"后训练"落地为
**FinGPT 风格管线的参数校准**（KNN 权重 / 评分权重 / 概率阈值 / 提示词）。

## 2. 数据源（已就位）

| 数据 | 路径 | 内容 |
|---|---|---|
| 市场反馈 | `docs/data/llm/market_feedback.json` | 预测 vs 实际、RLSP 样本、alignment_rate |
| 稳健组合绩效 | `docs/data/paper/performance.json` | 每日组合收益 + 每只预测概率 vs 实际涨跌 |
| 激进组合绩效 | `docs/data/paper/performance_aggressive.json` | 同上（高波动样本，区分度更大） |
| 全库扫描 | `docs/data/paper/aggressive_scan.json` | 全部自选股的激进分与概率 |

## 3. 触发条件

- 模拟盘对决（稳健 vs 激进 vs 等权基准）积累 **≥3 个交易日**（预计 2026-08-12 起）
- 或 market_feedback 样本数 ≥ 200
- 满足其一即可启动第一轮调参；优先等 5 个交易日以获得更稳结论

## 4. 第一轮调参点（候选，按校准报告决定）

1. **概率阈值**：若"预测 3日概率 ≥60%"的股票实际胜率明显低于 60%（乐观偏差），
   将 daily_brief 候选阈值从 50% 上调（如 60%/65%），并同步 aggressive_scan 权重
2. **评分权重**：对比技术面/基本面/行业分与实际表现，调整
   `src/analysis/scoring.py` 中 TECHNICAL_WEIGHT / FUNDAMENTAL_WEIGHT 或 KNN 特征权重
3. **提示词**：若 AI 研报/明日关注重复出现"过度乐观"措辞，更新
   `src/llm/` 与 `src/strategies/daily_brief.py` 的 system prompt（加校准约束）
4. **组合策略**：若激进组合连续跑赢稳健组合，提高 aggressive_scan 的动量权重；
   若跑输/大亏，降低动量权重或加入止损纪律

## 5. 验证方式（后训练的闭环）

- 调参前后各统计 5 个交易日的 `alignment_rate`（预测方向 vs 实际方向一致率）
- 对比稳健/激进/等权基准的累计收益曲线
- 只有当校准率提升且组合不显著跑输基准时，判定该轮后训练有效
- 每轮调参记录在 `测试记录/` 或本文件追加"调参日志"

## 6. 调参日志

（等待首轮数据，2026-08-12 后填写）