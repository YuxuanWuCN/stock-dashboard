# 板块轮动使用指南（USER_GUIDE）

面向日常使用者：如何跑每日决策、看懂输出、处理告警、查看前端卡片。

## 1. 快速开始

```powershell
cd Rainbow_FinGPTv2
# 离线演练（代理情绪，不发起任何外部请求）
.\.venv\Scripts\python.exe tools\sector_rotation_daily.py --mode proxy

# 真实情绪模式（需新闻数据可达；无新闻自动降级代理并在 notes 中说明）
.\.venv\Scripts\python.exe tools\sector_rotation_daily.py            # auto 模式

# 离线复现指定新闻 + 启用 LLM 复核
.\.venv\Scripts\python.exe tools\sector_rotation_daily.py --mode llm --news-fixture news.json --use-advisor
```

产物：
- `docs/data/sector_rotation/latest_rotation.json` —— 当日决策（覆盖写）
- `docs/data/sector_rotation/history.jsonl` —— 历史决策归档（只追加）
- `reports/sector_rotation/alerts_YYYYMMDD.json` —— 监控告警

## 2. 读懂输出

CLI 首行示例：

```
[sector_rotation_daily] trade_date=2026-08-27 sentiment_source=price_breadth_proxy holding=gold should_rotate=False target=None conf=0.0000
```

| 字段 | 解读 |
|---|---|
| `sentiment_source` | `price_breadth_proxy`=价格宽度代理（**仅机制演练，禁作结论**）；`llm_news_replay`=真实新闻情绪 |
| `holding` | 决策后的持仓板块：green=绿色新能源 / storage=存储芯片 / gold=黄金避险（防御板块） |
| `should_rotate=False` + 代理模式 | 正常现象：代理分数最高恰为 0.5，严格大于 0.5 的门槛永不触发（护栏设计，见 DESIGN.md §2.2） |
| `conf` | 决策置信度；代理模式下通常低值 |

**重要**：在真实 LLM 情绪累积 ≥20 个交易日并通过 S2 覆盖门槛（Sharpe 提升 ≥0.3 且最大回撤 ≤20%）之前，`strategy_validated` 恒为 `false` —— 轮动建议仅供参考，不构成结论性投资建议。

## 3. 每日流水线中的位置

`tools/daily_routine.py` 的 `6b/9 板块轮动决策与归档` 自动执行本任务（`allow_fail=True`：失败不阻断后续步骤）。无人值守下 auto 模式若抓不到新闻，会以代理降级并在 `notes` 标注"降级"。

## 4. 监控告警响应

| 告警 | 级别 | 处置 |
|---|---|---|
| `freshness.kline` critical | K 线缺失/严重滞后 | 先修复 K 线抓取（docs/data/kline），再重跑 daily |
| `freshness.rotation` warning | 当日任务未跑/失败 | 手动执行 CLI 或查 daily_routine 日志 |
| `validity.sentiment_bounds` critical | 情绪分越界 | 数据污染信号：检查上游聚合与 provider，勿信任当日产物 |
| `validity.sample_size` warning | 板块样本不足 | 已知缺失票（688123/002049/600362）可容忍；新增缺失需补抓 K 线 |
| `behavior.*` critical | 引擎硬约束被破坏 | **回归 Bug**：停止使用该产物，按质量门禁流程登记修复 |
| `llm.*` warning | 复核不可用/分歧 | 不影响量化结论有效性；连续不可用需检查 LLM 配置 |

CLI 退出码 `3` = 存在 critical 告警，流水线日志会体现。

## 5. 前端卡片

启动 dashboard 后，首页"板块轮动"卡片显示：三板块评分（零轴居中评分条）、当前持仓、是否轮动、LLM 复核状态（agreed/diverged/unavailable 三态）、数据时间与诚实性标注。`stale`（默认超过 5 个交易日未更新，`SECTOR_ROTATION_STALE_DAYS` 可调）时卡片顶部出现过期徽章；缺数据显示空态（不伪造数据）。

## 6. 常见问题

- **想看轮动真的会发生时的参数演练？** 用回测敏感性场景：`tools/sector_rotation_run_scenarios.py --allow-overwrite`（S3 将 target_threshold 下修至 0.3/0.4 触发轮动；产出仅验证机制链路，见 BACKTEST_REPORT.md §5）。
- **能手动改 latest_rotation.json 吗？** 不能。持仓状态由 `history.jsonl` 反推，手改会造成行为约束复核（monitoring）报 critical。重跑 CLI 即可（同日重复运行以最后一次为准）。
- **离线无 API key 会失败吗？** 不会。`--mode proxy` 与夹具模式完全离线；auto 模式抓不到新闻时降级代理而非报错。
