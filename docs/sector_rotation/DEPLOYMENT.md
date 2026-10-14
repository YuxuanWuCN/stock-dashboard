# 板块轮动部署与运维（DEPLOYMENT）

面向部署者：环境要求、每日流水线接入、API/前端发布、回退方式与告警响应 SOP。

## 1. 环境要求

- Python ≥3.12（项目 `.venv`），依赖见 `requirements.txt`（板块轮动模块本身仅依赖标准库 + numpy/pandas 经既有回测链路）
- K 线数据：`docs/data/kline/{code}.json`（由既有抓取流水线维护；板块轮动只读）
- 可选：LLM API key（`.env`，仅 `--mode llm`/auto 命中新闻时需要；`proxy`/夹具模式完全离线）
- 前端：Node ≥18（`rainbow-fingpt-web`，构建 `npm run build` = `tsc -b && vite build`）

## 2. 部署步骤

1. **后端**：板块轮动无独立进程。`daily_job` 由 `tools/daily_routine.py` Step `6b/9` 触发；Flask server（`src/server.py`）随 dashboard 启动，`/api/sector_rotation` 自动可用。
2. **前端**：`rainbow-fingpt-web` 正常构建发布即可，板块轮动卡片已挂载于主页（MainGrid 与风险雷达之间）。
3. **定时**：保持既有 daily_routine 计划任务不变（6b 步已内置）；如需单独调度：
   ```powershell
   .\.venv\Scripts\python.exe tools\sector_rotation_daily.py   # auto 模式，退出码 0/2/3
   ```
4. **可调参数**（环境变量）：
   | 变量 | 默认 | 作用 |
   |---|---|---|
   | `SECTOR_ROTATION_STALE_DAYS` | 5 | API/前端判定产物过期的交易日数 |
   风控阈值（持仓/冷却/月上限等）**只能**改 `src/sector_rotation/config.py`（单一来源），改后须过门禁。

## 3. 发布验收清单

- [ ] `.\.venv\Scripts\python.exe -m pytest tests/sector_rotation -q` 全绿
- [ ] `tools/sector_rotation_daily.py --mode proxy` 退出码 0，`latest_rotation.json` 更新
- [ ] `GET /api/sector_rotation` 返回 `status ∈ {ok, stale}` 且 `data.sentiment_source` 正确
- [ ] 前端卡片显示三板块评分与诚实性标注（代理模式必须显示"仅作决策参考"类标注）
- [ ] `reports/sector_rotation/alerts_YYYYMMDD.json` 无 `behavior.*` critical

## 4. 回退方式

板块轮动是**旁路功能**，回退不影响主链路：

1. 停止产出：daily_routine 移除/禁用 Step 6b（或临时把 `sector_rotation_daily.py` 调用注释）；
2. API 降级：删除 `docs/data/sector_rotation/latest_rotation.json` → `/api/sector_rotation` 返回 `missing`（200），前端自动显示空态，不报错；
3. 代码回退：`git revert` 相应提交即可（无数据库 schema、无外部状态依赖；`history.jsonl` 为追加式归档，回退代码不会破坏既有行）。

**禁止**通过手工编辑 `latest_rotation.json`/`history.jsonl` 伪造历史决策——monitoring 的行为约束复核会报 critical，且违反数据诚实性红线。

## 5. 告警响应 SOP

| 场景 | 信号 | 响应 |
|---|---|---|
| 每日任务未跑 | API `stale` / `freshness.rotation` warning | 查 daily_routine 日志 → 手动补跑 CLI（指定 `--trade-date` 会被回落处理，非交易日安全） |
| K 线断更 | `freshness.kline` critical | 属于上游数据流水线问题：先修抓取，板块轮动自动随下次 daily 恢复 |
| 情绪分越界/板块缺失 | `validity.*` critical | 当日产物不可信：通知使用方看"过期/降级"标注，登记 Bug 走质量门禁流程 |
| 行为约束违例 | `behavior.*` critical | 引擎回归 Bug：立即停用产物（删 latest 或忽略），按 Rainbow 门禁流程 begin-unit 修复 |
| LLM 复核长期不可用 | `llm.unavailable_rate` warning | 量化结论仍有效；检查 API key/网络后视需要恢复复核 |

## 6. 数据归档与复现

- 回测产物：`data/processed/sector_rotation/backtest/{window}/{variant}/`（nav/trades/decisions/sector_states/metrics/run_manifest），manifest 记录 provider、参数、输入哈希与 git commit，支持逐场景复现。
- 前向观察计划：`history.jsonl` 累积 ≥20 个真实 LLM 情绪交易日后，重跑 S2（`tools/sector_rotation_run_scenarios.py`）评估是否达到覆盖门槛，达标才允许把 `strategy_validated` 置真。
