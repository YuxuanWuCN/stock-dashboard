# 数据模型: Fama-MacBeth 多因子引擎（Phase 1）

**Feature**: 003-fama-macbeth-engine | **Date**: 2026-08-15 | **来源**: spec.md Key Entities + research.md 决策

## 1. FactorSeries（因子序列）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| date | TEXT (ISO YYYY-MM-DD) | 唯一、非空、单调递增 | 交易日 |
| mkt / smb / hml / mom | REAL | 允许少量缺失（缺口率 <= 5%，阈值可配置） | Carhart 4 因子值 |
| rf | REAL | 可空 | 无风险日利率；缺省用固定近似（年化 2.5%/252，可配置） |
| source | TEXT | 非空 | 来源标识（如 CSMAR 导出批次号） |
| version | TEXT | 非空 | 数据版本标识 |

验证规则：重复日期入库时 UPSERT（后写覆盖并告警）；连续缺失日期清单进入数据质量报告。

## 2. FactorDatabase（SQLite 因子库）

- 路径：docs/data/factors/factors.db
- 表 factors(date TEXT PRIMARY KEY, mkt REAL, smb REAL, hml REAL, mom REAL, rf REAL)
- 表 source_meta(key TEXT PRIMARY KEY, value TEXT)：source、version、imported_at、row_count、min_date、max_date、gap_rate
- 状态转换：空库 → 导入（幂等 UPSERT）→ 就绪；导入失败 → 保持原状态并报错（绝不半写：事务回滚）

## 3. RegressionResult（回归结果）

| 字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| code | TEXT | 非空 | 标的代码 |
| window_start / window_end | TEXT | 非空 | 5 年锚定窗口（截至分析日） |
| alpha | REAL | 非空（或 null=数据不足） | 阶段一截距（日频） |
| alpha_p_value | REAL | [0,1] | HAC(Newey-West, maxlags=5) 标准误下 p 值 |
| information_ratio | REAL | 非空 | alpha / sigma(residual) |
| betas | OBJECT | 4 键 | {mkt, smb, hml, mom} |
| vif | OBJECT | 4 键 | 各因子 VIF，共线性诊断 |
| n_obs | INTEGER | >= 1 | 有效观测数；< 最小窗口(默认 250) 时整体输出 null + 原因 |
| converged | BOOLEAN | 非空 | 回归收敛状态 |

验证规则：数据不足（默认 < 1 年）→ 整条 null + reason 字段（FR-009，不伪造）。

## 4. AlphaGateVerdict（门控判定）

| 字段 | 类型 | 取值 | 说明 |
|---|---|---|---|
| verdict | TEXT | pass / reject | p < 0.05 且 IR >= 0.3 → pass |
| reject_reason | TEXT | statistical / economical / insufficient_data / null | 拒绝原因枚举 |
| regression | RegressionResult | 引用 | 关联回归结果 |

状态转换：候选 → (回归) → pass 进激进组合候选池；reject → Watchlist 并记录原因。

## 5. RankingEntry 扩展（ranking.json 与 {code}.json）

- 新增 alpha_gate 字段组：{ verdict, alpha, alpha_p_value, information_ratio, betas, window_end, reject_reason? }
- 与现有 schema（src/analysis/schema.py）同步扩展校验；旧字段不变（向后兼容）
- 审计不变量：pass 的标的必然出现在激进组合候选；ranking.json 中 gate 字段与 {code}.json 一致

## 实体关系

```
FactorDatabase (factors, source_meta)
      │ 对齐（交集 + 剔除记录）
      ▼
每标的 5 年超额收益序列 ──阶段一 OLS──> RegressionResult (alpha/p/IR/betas/vif)
      │                                            │
      └── 阶段二横截面 FM（信息性）──────────────┘ → 报告
RegressionResult ──硬门控──> AlphaGateVerdict ──> RankingEntry.alpha_gate
```