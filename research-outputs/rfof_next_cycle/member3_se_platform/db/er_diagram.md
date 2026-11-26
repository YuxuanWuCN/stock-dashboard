# R-FOF 下周期 · SQLite 业务与行为日志库 ER 图

> 本文件由 `db/er_diagram.py` 依据**实际库结构**自动生成，请勿手改；
> 修改 `db/schema.sql` 后运行 `python db/er_diagram.py` 重新生成。

## 1. 实体关系（Mermaid）

```mermaid
erDiagram
    user_profiles {
        INTEGER profile_id PK
        TEXT session_id NOT NULL
        TEXT age_group NOT NULL
        TEXT cohort NOT NULL DEFAULT
        TEXT ab_group NOT NULL
        TEXT consent_scope NOT NULL DEFAULT
        TEXT device_class NOT NULL DEFAULT
        TEXT client_zone
        TEXT created_at NOT NULL DEFAULT
        TEXT updated_at NOT NULL DEFAULT
    }
    survey_responses {
        INTEGER response_id PK
        TEXT session_id NOT NULL
        TEXT instrument NOT NULL
        TEXT item_code NOT NULL
        REAL item_value NOT NULL
        INTEGER sequence NOT NULL DEFAULT
        TEXT answered_at NOT NULL DEFAULT
    }
    lifecycle_ledger {
        INTEGER ledger_id PK
        TEXT strategy_id NOT NULL
        TEXT scenario NOT NULL
        TEXT trade_date NOT NULL
        REAL nav NOT NULL
        REAL daily_return
        REAL drawdown NOT NULL
        REAL locked_floor NOT NULL
        TEXT source_sha256
    }
    ui_ab_events {
        INTEGER event_id PK
        TEXT event_uuid NOT NULL
        TEXT session_id NOT NULL
        TEXT ab_group NOT NULL
        TEXT age_group NOT NULL
        REAL scenario_dd NOT NULL
        TEXT event_type NOT NULL DEFAULT
        INTEGER panic_redeem_clicked NOT NULL DEFAULT
        INTEGER decision_latency_ms NOT NULL
        REAL comprehension_score NOT NULL DEFAULT
        TEXT client_ts
        TEXT server_ts NOT NULL DEFAULT
        TEXT source NOT NULL DEFAULT
        TEXT export_batch
    }
    user_profiles ||--o{ survey_responses : "session_id -> session_id"
    user_profiles ||--o{ ui_ab_events : "session_id -> session_id"
```

## 2. 关系口径

| 父表 | 子表 | 关系 | 说明 |
| --- | --- | --- | --- |
| `user_profiles.session_id` | `survey_responses.session_id` | 1 : N，级联删除 | 同一匿名会话可提交多份量表 |
| `user_profiles.session_id` | `ui_ab_events.session_id` | 1 : N，级联删除 | 交互事件按会话归档 |
| `lifecycle_ledger` | — | 独立事实表 | 策略×情景×交易日的逐日净值/回撤/棘轮账本 |

## 3. 字段字典

### user_profiles

| 字段 | 类型 | 约束 | 默认值 |
| --- | --- | --- | --- |
| `profile_id` | INTEGER | PK | — |
| `session_id` | TEXT | NOT NULL | — |
| `age_group` | TEXT | NOT NULL | — |
| `cohort` | TEXT | NOT NULL | 'online' |
| `ab_group` | TEXT | NOT NULL | — |
| `consent_scope` | TEXT | NOT NULL | 'analytics_only' |
| `device_class` | TEXT | NOT NULL | 'unknown' |
| `client_zone` | TEXT | — | — |
| `created_at` | TEXT | NOT NULL | strftime('%Y-%m-%dT%H:%M:%fZ', 'now') |
| `updated_at` | TEXT | NOT NULL | strftime('%Y-%m-%dT%H:%M:%fZ', 'now') |

### survey_responses

| 字段 | 类型 | 约束 | 默认值 |
| --- | --- | --- | --- |
| `response_id` | INTEGER | PK | — |
| `session_id` | TEXT | NOT NULL | — |
| `instrument` | TEXT | NOT NULL | — |
| `item_code` | TEXT | NOT NULL | — |
| `item_value` | REAL | NOT NULL | — |
| `sequence` | INTEGER | NOT NULL | 0 |
| `answered_at` | TEXT | NOT NULL | strftime('%Y-%m-%dT%H:%M:%fZ', 'now') |

### lifecycle_ledger

| 字段 | 类型 | 约束 | 默认值 |
| --- | --- | --- | --- |
| `ledger_id` | INTEGER | PK | — |
| `strategy_id` | TEXT | NOT NULL | — |
| `scenario` | TEXT | NOT NULL | — |
| `trade_date` | TEXT | NOT NULL | — |
| `nav` | REAL | NOT NULL | — |
| `daily_return` | REAL | — | — |
| `drawdown` | REAL | NOT NULL | — |
| `locked_floor` | REAL | NOT NULL | — |
| `source_sha256` | TEXT | — | — |

### ui_ab_events

| 字段 | 类型 | 约束 | 默认值 |
| --- | --- | --- | --- |
| `event_id` | INTEGER | PK | — |
| `event_uuid` | TEXT | NOT NULL | — |
| `session_id` | TEXT | NOT NULL | — |
| `ab_group` | TEXT | NOT NULL | — |
| `age_group` | TEXT | NOT NULL | — |
| `scenario_dd` | REAL | NOT NULL | — |
| `event_type` | TEXT | NOT NULL | 'decision' |
| `panic_redeem_clicked` | INTEGER | NOT NULL | 0 |
| `decision_latency_ms` | INTEGER | NOT NULL | — |
| `comprehension_score` | REAL | NOT NULL | 0 |
| `client_ts` | TEXT | — | — |
| `server_ts` | TEXT | NOT NULL | strftime('%Y-%m-%dT%H:%M:%fZ', 'now') |
| `source` | TEXT | NOT NULL | 'web' |
| `export_batch` | TEXT | — | — |

## 4. 分析视图

* `v_ab_decision_stats`
* `v_ab_session_coverage`
* `v_survey_wide`
