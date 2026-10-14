# 板块轮动系统设计（DESIGN）

- 适用范围：`src/sector_rotation/` 全部模块与集成链路（CLI / Flask API / 前端卡片）
- 上位文档：`docs/specs/` 板块轮动规划；回测证据见 `BACKTEST_REPORT.md`；数据边界见 `DATA_FEASIBILITY.md`
- 状态：**未验证策略**。在 S2（真实 LLM 情绪 × W_real）覆盖门槛确认前，所有产物 `strategy_validated=False`，仅可作为决策参考，禁止作为结论性投资建议。

## 1. 模块边界与数据流

```
docs/data/kline/*.json ──┐
src/llm/news_fetcher.py ─┤→ backtest/sentiment_providers.py ──→ sector_sentiment_aggregator.py
src/llm/llm_sentiment.py ┘        (SentimentProvider 协议)             (个股→板块情绪)
                                       │                                    │
                                       ▼                                    ▼
                              daily_job.run_daily ◄──── sector_rotation_engine.decide()
                              (latest_rotation.json      (风控门禁 + 轮动决策，≤100ms 纯量化)
                               + history.jsonl)                  │
                                                                 ▼
                                                       llm_decision_advisor（可选复核，
                                                       只回填 llm_validation，不推翻量化）
daily_job 产物 ──→ monitoring.run_monitoring ──→ reports/sector_rotation/alerts_YYYYMMDD.json
daily_job 产物 ──→ src/server.py /api/sector_rotation ──→ rainbow-fingpt-web 板块轮动卡片
```

| 模块 | 职责 | 禁止事项 |
|---|---|---|
| `config.py` | 板块/成分股/阈值常量单一来源 | 散落魔法数字到各模块 |
| `sector_sentiment_aggregator.py` | 个股情绪 → 板块情绪（置信度加权、趋势判定） | 伪造缺失板块分数 |
| `sector_rotation_engine.py` | 硬门禁（最短持仓/冷却/月上限/目标情绪门槛）+ 轮动决策 | 被 LLM 输出推翻量化结论 |
| `llm_decision_advisor.py` | 可选复核与归因，全量审计落盘 | 静默降级（降级必须 `status=unavailable`） |
| `position_manager.py` | 3 日渐进换仓（50%/30%/20%）与成本核算 | 超出 `MAX_TOTAL_ROTATION_COST` 继续切换 |
| `backtest/` | 可插拔情绪 provider + as-of 严格回测 + 指标 | 未来函数；代理情绪冒充实测 |
| `daily_job.py` | 每日决策与归档（latest_rotation.json + history.jsonl 追加） | 覆盖历史；无新闻时谎报 LLM 来源 |
| `monitoring.py` | 四类告警（新鲜度/合法性/行为约束/LLM 健康） | 把 critical 吞成日志 |

## 2. 关键设计决策

1. **情绪 provider 可插拔 + 来源强制标注**。个股日频情绪序列在本仓库不存在（见 `DATA_FEASIBILITY.md`），因此回测与每日任务的输入统一走 `SentimentProvider` 协议，所有产物携带 `sentiment_source ∈ {price_breadth_proxy, llm_news_replay, frozen_fixtures}`。代理分数只做机制验证，禁止支撑报告结论（`report_usable=False`）。
2. **代理情绪的饱和特性**。`ProxyBreadthSentimentProvider` 截面标准化后板块最高分恰为 0.5，而候选门槛 `MIN_TARGET_SENTIMENT=0.5` 为严格大于——代理模式下**永不触发轮动**是设计内行为（S1 回测 rotations=0 即证）。这不是缺陷，是防止代理分数被当景气信号的护栏；S3 敏感性场景须显式下修门槛。
3. **LLM 复核单向注入**。`decide(..., advisor, llm_validation_enabled)` 在量化决策定稿后执行一次复核：同意→`agreed`；反对→记录 `diverged` 但保留量化 `should_rotate`；异常/超时/降级→`unavailable`。默认 `advisor=None` 时零行为变化。
4. **持仓状态从 history.jsonl 反推**（`infer_portfolio_state` 纯函数）。轮动行以 `target_sector` 为准（`_effective_holding`），首日无历史使用宽松状态（防御板块 + 超冷却天数），避免风控门禁误拦首日决策。
5. **数据诚实性贯穿前端**。API 与卡片透传 `sentiment_source / report_usable / strategy_validated / notes`；前端 hook 不做 mock 兜底，缺数据显式空态。
6. **监控独立复核**。`monitoring.py` 不信任引擎，直接从 `history.jsonl` 手算复核月内轮动次数、最短持仓、冷却期违例——引擎若出回归 Bug，监控以 critical 告警兜底（CLI 退出码 3，经 daily_routine 日志机制暴露）。

## 3. 交易与风控参数（单一来源：`config.py`）

| 参数 | 值 | 语义 |
|---|---|---|
| `MIN_HOLDING_DAYS` | 5 | 最短持仓交易日 |
| `COOLDOWN_DAYS` | 7 | 两次轮动最小间隔 |
| `MAX_ROTATION_PER_MONTH` | 3 | 自然月轮动上限 |
| `MIN_TARGET_SENTIMENT` | 0.5 | 目标板块情绪严格下限 |
| `SENTIMENT_DECLINE_THRESHOLD` | -0.3 | 当前板块下沉判定 |
| `ROTATION_EXECUTION_DAYS` | 3 | 渐进换仓天数 |
| `MAX_TOTAL_ROTATION_COST` | 0.01 | 单次切换累计成本上限 |
| `DEFENSIVE_SECTOR` | gold | 极端行情防御板块 |

## 4. 已知局限

- `W_real` 为空窗：真实 LLM 情绪的历史重放尚不可行，S2 结论性场景降级为前向累积观察（`history.jsonl` 累积 ≥20 交易日真实情绪后重跑）。
- 成分股 K 线缺失（688123/002049/600362）：板块净值按可用子集等权，监控以 `validity.sample_size` warning 显式登记。
- 代理情绪与真实景气的映射未经验证：代理分数仅供机制演练。
