# 板块轮动接口契约（API）

- 覆盖：`/api/sector_rotation`（Flask）、`latest_rotation.json` / `history.jsonl` 产物 schema、CLI 与退出码
- 原则：**缺数据不 500、降级不静默、来源必标注**。任何消费方以 `sentiment_source / report_usable / strategy_validated` 三个字段判断结果可信级别。

## 1. GET /api/sector_rotation

- 数据源：`docs/data/sector_rotation/latest_rotation.json`
- CORS：与其他 `/api/*` 一致（`*`）
- 失败语义：文件缺失/损坏一律 `200` + 状态字段，不抛 500

```jsonc
// status ∈ "ok" | "stale" | "missing" | "error"
{
  "status": "stale",
  "age_trading_days": 34,          // trade_date 距今日的weekday数；解析失败时 null
  "stale_threshold_days": 5,       // 环境变量 SECTOR_ROTATION_STALE_DAYS 可调（默认 5）
  "sentiment_source": "price_breadth_proxy",
  "report_usable": false,
  "strategy_validated": false,
  "data": { /* latest_rotation.json 原文，missing/error 时为 null */ },
  "message": "..."                 // 仅 missing/error 出现
}
```

判定规则：
| 条件 | status |
|---|---|
| 文件不存在 | `missing` |
| JSON 解析/读取失败 | `error` |
| `age_trading_days > stale_threshold_days` 或 trade_date 不可解析 | `stale` |
| 其余 | `ok` |

## 2. latest_rotation.json schema（schema_version=1.0）

| 字段 | 类型 | 说明 |
|---|---|---|
| `generated_at` | str | ISO 秒级时间戳（生成时刻，非决策时刻） |
| `trade_date` / `requested_trade_date` | str | 实际决策日 / 请求日（请求日非交易日时回落到日历末） |
| `sentiment_source` | str | `price_breadth_proxy` \| `llm_news_replay` |
| `report_usable` | bool | 代理情绪恒 false（禁作结论） |
| `strategy_validated` | bool | S2 覆盖门槛确认前恒 false |
| `holding_sector` | str | 决策后持仓板块（轮动= target，否则 current） |
| `portfolio_state` | obj | `current_sector/holding_days/monthly_rotations/days_since_last_rotation`（history 反推） |
| `sectors` | obj | 板块 id → `{name, sentiment_score, sentiment_trend, confidence, stock_count,...}` |
| `decision` | obj | `RotationDecision.to_dict()`（should_rotate/target_sector/reason/confidence/metrics） |
| `reason` / `confidence` | str / float | 决策理由与置信度（顶层冗余，前端直读） |
| `llm_validation` | obj\|null | `{status: agreed\|diverged\|unavailable,...}`；未启用复核时为引擎输出 |
| `audit` | obj | `engine/engine_version/decision_path_ms/python/git_commit/portfolio_state_used/provider/sector_inputs/advisor_audit` |
| `notes` | list[str] | 降级与数据说明（如 auto 模式无新闻降级） |
| `history_days_recorded` | int | history.jsonl 既有行数（不含本次追加） |

## 3. history.jsonl（追加式，前向累积真实情绪序列用）

每行紧凑 JSON：`trade_date, sentiment_source, current_sector, holding_sector, should_rotate, target_sector, is_fallback, confidence, sector_scores{sid}, sector_trends{sid}, llm_validation_status, generated_at`。
同一 `trade_date` 重复运行会追加多行，**以最后一行为准**（`load_history` 与 `infer_portfolio_state` 按此语义读取；坏行跳过不中断）。

## 4. CLI

```
python tools/sector_rotation_daily.py [--trade-date YYYY-MM-DD] [--mode auto|llm|proxy]
    [--news-fixture news.json] [--use-advisor] [--out-dir DIR] [--no-monitor]
```

| 退出码 | 含义 |
|---|---|
| 0 | 成功且监控无 critical |
| 2 | 参数/数据错误（无 K 线日历等），stderr 给出异常类型与消息 |
| 3 | 决策成功，但 `run_monitoring` 判定存在 `severity=critical` 告警 |

每日流水线：`tools/daily_routine.py` Step `6b/9 板块轮动决策与归档`（`allow_fail=True`，失败不阻断后续步骤，退出码记录于日志）。

## 5. 监控产物 reports/sector_rotation/alerts_YYYYMMDD.json

```jsonc
{
  "schema_version": "1.0",
  "generated_at": "...", "rotation_trade_date": "...", "calendar_last_date": "...",
  "history_days_recorded": 2,
  "has_critical": false,
  "summary": {"info": 0, "warning": 1, "critical": 0},
  "alerts": [ {"check": "validity.sample_size", "severity": "warning",
               "message": "板块 storage 样本数 4 低于预期 6",
               "detail": {"sector": "storage", "stock_count": 4, "expected": 6}} ]
}
```

告警 check 命名空间：`freshness.*`、`validity.*`、`behavior.*`（critical=引擎硬约束被破坏）、`llm.*`（一律 warning，复核不可用不影响量化结论有效性）。

## 6. 前端消费（rainbow-fingpt-web）

- `hooks/useSectorRotation.ts` → `fetchSectorRotation()`；**无 mock 兜底**：`missing/error` 返回 `data=null`，卡片显示空态。
- `sections/SectorRotationSection.tsx` 渲染条件：状态徽章（ok/stale/missing/error）→ 三板块评分卡 → 决策行 → 底部诚实性标注（`sentiment_source`、`strategy_validated`、`notes`）。
