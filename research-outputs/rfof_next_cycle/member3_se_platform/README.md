# R-FOF 下周期 · 软工程平台（成员 3 / SE）

对应 Issue **#14**：把原本散落的 CSV/JSON 与静态网页，升级为 **DuckDB + SQLite 双库底座**、
**去焦虑 A/B 埋点交互系统**与**自动化测试体系**，直接服务 #12（信管 A，真实资产回测）与
#13（信管 B，问卷与 A/B 统计检验）。

> 口径声明：本目录里的界面金额（本金 ¥300,000、安全垫 85%、−10%/−20% 后的余额）是**交互原型示意**，
> 不是回测结论。真实净值序列一律由 #12 的 `member1_asset_quant` 产出后灌入 `lifecycle_ledger`。

---

## 1. 交付物一览

```
member3_se_platform/
├── db/
│   ├── schema.sql          # SQLite DDL：4 张表 + 3 个视图 + 索引 + 约束 + 触发器
│   ├── connection.py       # 连接工厂：PRAGMA/外键/只追加表写保护/幂等初始化
│   ├── dao.py              # 唯一写入口：校验、确定性分组、幂等事件、脱敏导出
│   ├── duck_reader.py      # DuckDB 只读时序接口（兼容 #12 的 MarketReader 协议）
│   ├── export.py           # 脱敏 CSV 导出 + 可复核清单
│   ├── er_diagram.py       # 从真实库结构反向生成 Mermaid ER 图
│   ├── er_diagram.md       # 自动生成的 ER 图与字段字典
│   └── init_db.py          # 初始化 CLI（建库、校验、生成 ER）
├── ab_webapp/
│   ├── index.html          # 单文件零构建 A/B 前端（A 常规波动 / B 适老去焦虑 / 离线导出）
│   └── server.py           # Flask 本地 API（会话、事件、问卷、离线导入、统计、导出）
├── tests/                  # 128 个单元测试（schema/DAO/DuckDB/API/前端契约）
└── README.md
```

仓库级集成测试：`tests/test_rfof_se_platform_integration.py`（建库 → API → 视图 → 导出 → pandas 复算）。

---

## 2. 一键本地启动

```bash
# 在仓库根目录
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd research-outputs/rfof_next_cycle/member3_se_platform

../../../.venv/bin/python db/init_db.py --db data/rfof_ab.sqlite3   # 建库 + ER 图
../../../.venv/bin/python ab_webapp/server.py --db data/rfof_ab.sqlite3 --port 8000
```

浏览器打开：

* 参与者视角：<http://127.0.0.1:8000/>
* 评审视角（A/B 并排）：<http://127.0.0.1:8000/?role=reviewer>

无 Python 环境的社区平板：直接把 `ab_webapp/index.html` 拷到平板，用浏览器打开
（`file://` 协议可离线运行，页面零 CDN 依赖），体验完后点「导出离线 JSON / CSV」，再由组织者导入：

```bash
curl -X POST http://127.0.0.1:8000/api/import \
     -H 'Content-Type: application/json' \
     --data-binary @rfof_ab_offline_1700000000000.json
```

同一离线包重复导入是幂等的（`event_uuid` 去重），不会把样本量刷大。
离线包内含原始 `session_id`（导入时需要），请只在受控设备间传递，导入完成后删除本地文件。

---

## 3. 双库分工

| 用途 | 技术 | 位置 | 只读/可写 | 说明 |
| --- | --- | --- | --- | --- |
| 时序行情与因子面板 | DuckDB + Parquet | `data/task_split/csmar_master/csmar_factor_panel_master.parquet` | 只读 | 299 只股票 / 192,199 行 / 2024-01-02 → 2026-08-28；`db/duck_reader.py` 封装 |
| 业务与行为日志 | SQLite 3 | `data/rfof_ab.sqlite3`（运行时生成，不入库） | 写入口唯一为 `db/dao.py` | 4 张表 + 3 视图；WAL；外键级联；`ui_ab_events` 连接层禁改 |

DuckDB 只读的三层保证：

1. 只在内存库中通过 `read_parquet` / `read_csv` 访问文件，不打开可写库文件；
2. `_guard()` 只放行 `SELECT` / `WITH` 开头的单条语句，拒绝 DDL/DML/分号拼接；
3. 文件路径全部走参数绑定，不做字符串拼接。

`lifecycle_ledger` 是可从 #12 净值序列重建的派生账本，允许幂等 upsert；
`ui_ab_events` 是实验原始日志，连接层 authorizer 直接拒绝 `UPDATE`/`DELETE`（`sqlite3.DatabaseError`），
保证“已落库的行为记录不可就地篡改”。

---

## 4. 数据模型

ER 图（Mermaid，由 `python db/er_diagram.py` 依据真实库结构自动生成）：见 [`db/er_diagram.md`](db/er_diagram.md)。

| 表 | 作用 | 关键约束 |
| --- | --- | --- |
| `user_profiles` | 匿名会话画像 | `session_id` 唯一；`ab_group`/`age_group`/`cohort` 创建后不可改（触发器）；枚举 CHECK |
| `survey_responses` | 问卷长表（SUS / LSI / 规则测验） | `(session_id, instrument, item_code)` 唯一；SUS/LSI ∈ [1,5]，quiz ∈ {0,1} |
| `lifecycle_ledger` | 策略 × 情景 × 交易日的逐日账本 | `(strategy_id, scenario, trade_date)` 唯一；`nav>0`、`drawdown<=0`、`locked_floor>=0` |
| `ui_ab_events` | A/B 交互事件（Issue #14 约定字段） | `event_uuid` 唯一（幂等）；`scenario_dd ∈ {0,-10,-20}`；延迟 ∈ [0,3600000]；理解分 ∈ [0,3] |

分析视图（直接给 #13 取数）：

* `v_ab_decision_stats`：按 `ab_group × age_group × scenario_dd` 聚合决策数、恐慌赎回数、恐慌率、平均延迟、平均理解分；
* `v_ab_session_coverage`：会话覆盖与测验提交数（按组/年龄/渠道）；
* `v_survey_wide`：每会话 SUS 总分与规则测验总分。

`ui_ab_events` 字段与 #14 逐字对齐：
`session_id, ab_group, age_group, scenario_dd, panic_redeem_clicked, decision_latency_ms, comprehension_score`
（另有 `event_type`、`client_ts/server_ts`、`source`、`export_batch` 等采集辅助列）。

---

## 5. HTTP API

| 方法 | 路径 | 说明 | 失败语义 |
| --- | --- | --- | --- |
| GET | `/api/health` | schema 版本、DuckDB 可用性、真实面板行数 | — |
| POST | `/api/session` | 建立/取回匿名会话与确定性分组 | 400 参数非法；409 与既有画像冲突 |
| GET | `/api/session/<id>` | 查询会话 | 404 |
| POST | `/api/events` | 批量写事件（单请求 ≤ 500 条 / ≤ 2MB） | 400 字段非法；409 组别被篡改；413 超限 |
| POST | `/api/survey` | 写量表/测验作答（upsert） | 400 |
| POST | `/api/import` | 导入离线平板 JSON 包（幂等） | 400 |
| GET | `/api/stats` | 决策统计 + 覆盖率 | — |
| GET | `/api/export?table=…` | CSV 脱敏导出 | 400 未知表；403 非本机且无 token |

分组算法（前后端逐位一致，已用 42 组样本做跨语言校验）：

```text
ab_group = "A" if sha256("rfof-ab-v1:" + session_id)[0] % 2 == 0 else "B"
```

事件写入的完整性规则：

* `event_uuid` 幂等：离线补传重复批次只计一次，且**不覆盖**已落库事件的字段；
* 客户端若上报 `ab_group` / `age_group`，必须与画像一致，否则 409 拒绝（防隐藏实验臂污染）；
* 事件字典不允许夹带未知字段（例如 `real_name`），直接 400 拒绝；
* 批量写入在单事务内完成，任一事件非法则整批回滚。

---

## 6. 脱敏导出（交给 #13）

```bash
../../../.venv/bin/python db/export.py --db data/rfof_ab.sqlite3 --out exports/ --salt demo-salt
```

输出 `ui_ab_events.csv`、`user_profiles.csv`、`survey_responses.csv`、`lifecycle_ledger.csv`、
`v_ab_decision_stats.csv` 与 `export_manifest.json`。

* `session_id` 一律替换为 `session_ref = "S-" + sha256(salt + ":" + session_id)[:12]`；
* 默认盐持久化在库内 `schema_meta.export_salt`：**同一实验库的多次导出可互相关联**
  （events / survey / profiles 可 join），换库或显式 `--salt` 后不可关联、不可反查；
  CSV 响应头 `X-Export-Salt-SHA256` 只暴露盐哈希，便于组织者核对批次；
* 只导出**列白名单**，任何疑似姓名/手机号/身份证/IP 的列会被 `assert_no_identifier_columns` 直接拦下；
* 清单记录行数、列名、CSV 的 sha256 与盐的 sha256（不写盐本身），#13 可逐项复核。

#13 的统计入口示例：

```python
import pandas as pd
from scipy.stats import chi2_contingency

events = pd.read_csv("exports/ui_ab_events.csv", encoding="utf-8-sig")
decisions = events[events.event_type == "decision"]
table = pd.crosstab(decisions.ab_group, decisions.panic_redeem_clicked)
chi2, p, dof, expected = chi2_contingency(table)
```

---

## 7. 与 #12 / #13 的接口

### 给 #12（信管 A）：替换 pending 的本地 reader

`db/duck_reader.py` 的 `DuckDBMarketReader` 与
`member1_asset_quant/market.py` 的 `MarketReader` 协议同名同签名：

```python
import sys; sys.path.insert(0, "research-outputs/rfof_next_cycle/member3_se_platform/db")
from duck_reader import open_reader

reader = open_reader(repo_root, market_dir=None, factory=None)
panel = reader.stock_panel()                      # 全量真实面板（字符串代码/日期）
window = reader.stock_window("2026-01-01", "2026-08-28", codes=["000001", "600519"])
provenance = reader.panel_provenance()            # 行数/股票数/首末日/文件 sha256/与清单是否一致
```

行情快照 CSV（`etf_close/fund_nav/actions/futures_close`）由 #12 抓取脚本落盘到
`data/_raw_cache/rfof_issue12`（与 `member1_asset_quant/fetch_market.py` 的 `MARKET_DIR` 一致；
也可用环境变量 `RFOF_MARKET_DIR` 覆盖），仓库不提交；
缺文件时 `FileNotFoundError` 显式失败，`market_availability()` 可先探活，绝不静默填 0。

### 给 #13（信管 B）：问卷字段与实验事件

* 问卷：`instrument ∈ {sus, lsi, rules_quiz}`，`item_code ≤ 32` 字符，`sequence` 控制展示顺序；
* 实验事件：见第 4、5 节，`event_type ∈ {page_load, scenario_view, decision, quiz_submit}`；
* 导出后即可做卡方 / Fisher / Logistic（见第 6 节示例）。

---

## 8. 测试与质量门禁

```bash
# 本模块单元测试（128 项）
.venv/bin/python -m pytest -q research-outputs/rfof_next_cycle/member3_se_platform/tests

# 仓库级端到端集成测试
.venv/bin/python -m pytest -q tests/test_rfof_se_platform_integration.py

# 仓库质量门禁（已注册到 .quality-gates.json 的 small 阶段）
python tools/quality_gate.py small
```

覆盖范围：schema 约束/触发器/写保护、DAO 校验与幂等、DuckDB 只读守卫与缺文件、
API 会话/事件/问卷/导入/导出权限与超限、前端静态契约（零构建、双模视觉、埋点字段、
可访问性、离线兜底）、**JS 与 Python 跨语言 SHA-256/分组一致性**（有 node 时执行）。

---

## 9. 已知限制

* 本服务面向**匿名本地实验**，无登录体系：写接口对局域网开放；导出接口默认只允许回环地址，
  远程导出必须配置 `RFOF_EXPORT_TOKEN` 并携带 `X-Export-Token` 头；
* SQLite 走 WAL + 串行写，适合几十人规模的社区/校园同期采集，不适合高并发线上；
* 评审模式（`?role=reviewer`）只用于并排预览两组视觉与文案，同一次决策只写入当前分组的事件；
  正式对照实验仍按“一人一臂”的组间设计执行，隐藏分组标签、不可中途切换；
* 前端演示金额为界面示意，不可当作回测绩效引用；真实绩效以 #12 交付为准；
* 原始行情 CSV 与 SQLite 运行库均不入库（`.gitignore` 已排除，测试另设 20MB 二进制上限断言）；
* CHARLS/CHFS 校准、断缴留存与前景理论测算属于 #13 交付范围，本目录只提供数据与埋点底座。

---

## 10. 变更记录

* 2026-11-26：首个版本（schema v1）。SQLite 双库底座、DuckDB 只读接口、A/B 埋点前端与 API、
  128 项单元测试 + 4 项仓库级集成测试；ER 图自动生成；质量门禁 small 阶段注册。