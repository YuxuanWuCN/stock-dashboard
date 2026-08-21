# Research: 师叔 claw-quant 核心融合侦察（Phase 0）

## 问题

2.0版 排名主流程 = 风险分 + 技术分 + 行业分 + 相似度预测分，全是**历史股价滞后信息**。
师叔 claw-quant 的"真谛"是前沿消息（海关/现货/原厂报价）打破财报时滞 + 因子半衰期/拥挤度防
因子动物园 + 信念-执行分离 + 约束监管。四点均未落地（领先指标引擎只有合成假数据、不进评分）。

## 侦察结论（静态审阅 + 数据抽查）

| 层 | 师叔 claw-quant | 2.0版 现状 | 差距 |
|---|---|---|---|
| 前沿消息 | Fisher 货币环境 + 前沿抓取 | leading_indicators.py 仅合成数据，无 akshare | 真实数据 0% |
| SFM 因子 | IC/半衰期/拥挤度 | factor_db.py 只有 CSV 校验+SQLite；无质量指标 | 指标 0% |
| Graham 信念 | thesis 预期差 | 无 thesis/holdings 分离结构 | 0% |
| Markowitz+Damodaran | 组合构建+7约束 | strategies 有纸面组合，无约束引擎 | 约束 0% |

## 关键决策

1. **真实数据源**：原厂报价函/华强北盘口无稳定免费接口 → 用 akshare 免费源作"领先代理"：
   半导体/光通信 → 东财行业板块指数（stock_board_industry_hist_em）；
   新能源 → 碳酸锂期货主力（futures_main_sina LC0）；
   贵金属 → 上金所现货（spot_hist_sge Au99.99）。诚实标注代理语义，合成仅作降级。
2. **评分接入**：compute_composite_score 新增 leading 分量（权重 0.10，从 forecast/up_prob
   各挪 0.05）；领先分 0-100，50 中性，拐点 ±30 分档。**合成降级数据不给分**（不伪造）。
3. **半衰期口径**：以因子收益自相关衰减为预测力持续性代理（IC_k = corr(F_t, F_{t+k})）。
4. **信念-执行分离**：Thesis/Holdings 两个 dataclass；价格只更新盯市，失效条件才转 invalid。
5. **沙箱限制**：akshare 真实抓取在沙箱 15s 读超时 → 降级合成；真实数据由用户本地
   tools/fetch_leading_data.py 拉取。代码全部用 mock/夹具测试。

## 风险与缓解

- akshare 接口列名/符号变更 → _first_available 候选列名解析 + 异常隔离 + 降级
- 领先分量可能被技术分淹没 → 权重 0.10 起步可调，评分 reasons 可见
- 全量重跑触发 4 类真实抓取 → 类别级内存缓存（同类别只抓一次）
