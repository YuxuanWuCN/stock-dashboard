# 后端代码需求（v1.0 更新版）

## 1. 任务目标

本地 Python 管道，每个交易日 18:00 自动抓取 202 只自选股数据，生成排行榜、个股详情、AI 研报、策略信号、明日关注与模拟盘绩效。只负责数据与计算，不负责前端绘图，不实现自动交易。

## 2. 输入

`watchlist.csv` 固定列：`code,name,type,category`

- `type` 支持：`stock`（A股）、`hk`（港股）、`us`（美股）、`kr`（韩股）、`etf`（场内/场外基金）
- 代码格式：A股/韩股 6 位数字；港股 5 位数字（如 `00700`）；美股 1-6 位字母

## 3. 数据源（直连模式，环境变量 `STOCK_PROXY=direct` 强制绕过系统代理）

| 市场 | 主源 | 备用 |
|---|---|---|
| A股 | 新浪 `stock_zh_a_daily`（qfq） | 东财 `stock_zh_a_hist` |
| ETF/基金 | 东财 → 腾讯 → 天天基金净值 | — |
| 美股 | 腾讯 `us{CODE}.OQ` | `us{CODE}.N`（行数不足时自动回退） |
| 港股 | 腾讯 `hk{CODE}` | — |
| 韩股 | Naver Finance 日线 | — |

## 4. 主要模块

| 模块 | 职责 |
|---|---|
| `src/fetch_data.py` | 抓取 → K线JSON → summary/meta（含数据过期标记 stale） |
| `src/build_ranking.py` | 5年数据 → 指标 → KNN 相似预测 → 评分 → ranking.json + 个股详情 |
| `src/strategies/` | 启明星/金叉/涨停回调选股、狩猎场支撑位、市场温度 |
| `src/llm/` | FinGPT 风格管线：新闻情感、RAG、DeepSeek V4 Flash 深度研报、市场反馈 |
| `src/strategies/daily_brief.py` | 明日重点关注 AI 摘要（区分分析日与推荐日） |
| `tools/paper_portfolio.py` | 模拟盘绩效记录（稳健/激进多组合，含预测校准） |
| `tools/aggressive_scan.py` | 全库激进潜力扫描 |
| `tools/daily_local.ps1` | 每日自动化入口（计划任务 18:00） |

## 5. 关键规则

- 数据过期检测：个股最后交易日距今 > `STALE_DATA_DAYS`（默认 10 天）→ 标记 stale；stale 标的排排行榜末尾、不参与明日关注推荐
- 交易日口径：排行榜 trade_date 取"多数股票的交易日"（众数），避免盘中个别标的混入当日未收盘 bar
- 报告生成：已有 DeepSeek 深度报告自动跳过（增量、省费）；LLM 调用上限 `LLM_DAILY_CALL_LIMIT`（默认 800）
- 所有输出为静态 JSON（UTF-8），遵循《04-前后端共享数据合同.md》

## 6. 质量要求

- 时间序列不乱序；外部行情请求可 mock / 离线夹具复现
- 任何改动必须通过质量门禁（`tools/run_quality.ps1`）