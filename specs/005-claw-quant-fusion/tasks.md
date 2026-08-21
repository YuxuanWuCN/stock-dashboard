# Tasks: 师叔 claw-quant 核心融合进 2.0版 判断主流程

**Input**: /specs/005-claw-quant-fusion/（spec.md、plan.md）

**Tests**: 必含（FR-009 全路径覆盖；AGENTS.md 测试先行；外部请求 mock）

## Format: ID [P?] [Story?] 带文件路径的描述

---

## Phase 1: Setup

- [X] T001 运行 `tools/run_quality.ps1 begin-unit` 记录基线

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T002 [P] 在 src/analysis/leading_indicators.py 新增 fetch_real_leading_signal(category)：按 INDUSTRY_LEADING_MAP 调用 akshare 免费源，输出 data_source/series/momentum_metrics；异常降级 synthetic_fallback
- [X] T003 [P] 在 tests/ 新增 akshare mock 夹具：伪造海关/现货时间序列返回 + 抛异常场景

**Checkpoint**: 领先数据抓取骨架就绪

---

## Phase 3: User Story 1 - 领先指标接真实数据源 (Priority: P1) 🎯 MVP

**Goal**: LeadingIndicatorEngine 能按 category 抓真实数据，失败优雅降级合成

**Independent Test**: mock akshare 返回序列 → data_source=="akshare" 且动量/拐点正确；mock 抛异常 → synthetic_fallback 不 crash

### Tests for US1（先写，先失败）

- [X] T004 [P] [US1] 在 tests/test_leading_indicators.py 写抓取测试：mock 成功 → data_source=akshare + series；mock 失败 → synthetic_fallback + confidence=low；category=general → fallback

### Implementation for US1

- [X] T005 [US1] 实现 fetch_real_leading_signal 的 akshare 调用（海关/现货映射）+ 异常隔离 + 缺失值处理
- [X] T006 [US1] 新增 tools/fetch_leading_data.py：本地批量抓取入口（写 docs/data/leading_signals/*.json），沙箱不联网

**Checkpoint**: 真实数据抓取代码落地且 mock 测试通过

---

## Phase 4: User Story 2 - 领先信号进评分 (Priority: P1)

**Goal**: compute_composite_score 新增 leading 分量，浏览器排名可见变化

**Independent Test**: 构造 A(positive_reversal)/B(negative_reversal) 同技术行业分 → A 综合分 > B；结果含 leading_score

### Tests for US2（先写，先失败）

- [X] T007 [P] [US2] 在 tests/test_scoring_leading.py 写评分测试：positive_reversal 正贡献 / negative_reversal 负贡献 / none 中性向后兼容

### Implementation for US2

- [X] T008 [US2] 在 src/analysis/config.py 新增 OPPORTUNITY_WEIGHTS 的 leading 权重（小权重 ~10%）
- [X] T009 [US2] 在 src/analysis/scoring.py 新增 compute_leading_score + 并入 compute_composite_score（结果含 leading_score/reason）
- [X] T010 [US2] 在 src/build_ranking.py 把领先信号结果传入 analyze_single/composite，输出到 ranking.json
- [X] T011 [US2] 前端 docs/assets/app.js + index.html 展示领先信号（排名原因/详情页标签）

**Checkpoint**: 排名因领先信号可观测变化（浏览器可见）

---

## Phase 5: User Story 3 - 因子半衰期与拥挤度 (Priority: P2)

**Goal**: factor_db 新增半衰期/拥挤度，写入质量报告

**Independent Test**: 合成 IC 衰减序列 → 半衰期接近理论值；高相关因子 → crowded

### Tests for US3（先写，先失败）

- [X] T012 [P] [US3] 在 tests/test_factor_quality.py 写半衰期/拥挤度测试：合成 IC 衰减 → half_life 正确；高相关→crowded；样本不足→None

### Implementation for US3

- [X] T013 [US3] 新增 src/analysis/factor_quality.py：half_life(ic_series) + crowding(factor_returns)
- [X] T014 [US3] 在 src/analysis/factor_db.py 接入，写入 docs/data/factors/quality_report.json（新增字段，旧字段保留）

---

## Phase 6: User Story 4 - 信念-执行分离 (Priority: P2)

**Goal**: thesis(信念) 与 holdings(执行) 分离；价格波动不改 thesis

**Independent Test**: 价格下跌触发再验证 → holdings 盯市更新、thesis 不变；失效条件触发 → thesis invalid

### Tests for US4（先写，先失败）

- [X] T015 [P] [US4] 在 tests/test_thesis.py 写分离测试：价格波动不改 thesis；失效条件触发 → invalid；thesis 无 holdings 不报错

### Implementation for US4

- [X] T016 [US4] 新增 src/analysis/thesis.py：Thesis/Holdings 数据类 + 再验证逻辑
- [X] T017 [US4] 在 src/llm/report_generator.py 报告分栏呈现 thesis/holdings（可选接入）

---

## Phase 7: User Story 5 - 约束监管 (Priority: P3)

**Goal**: 组合约束引擎 7 类约束，超限截断/标记

**Independent Test**: 60% 权重被截断到 20% 上限并记录理由；行业集中超限标记

### Tests for US5（先写，先失败）

- [X] T018 [P] [US5] 在 tests/test_constraints.py 写约束测试：单标的超限截断；行业集中超限标记；全部通过无副作用

### Implementation for US5

- [X] T019 [US5] 新增 src/analysis/constraints.py：7 类约束 + 默认上限 + 违规记录
- [X] T020 [US5] 在 src/strategies/ 组合构建处接入约束引擎（纸面组合）

---

## Phase 8: Polish & Cross-Cutting

- [X] T021 质量门禁 small→medium→heavy 全绿；新增代码行覆盖 100%
- [X] T022 独立复核：构造 A/B 标的验证 leading 换位（不依赖测试数量）
- [X] T023 更新 quickstart.md（本地真实抓取步骤）+ 提交

---

## Dependencies & Execution Order

- Foundational（T002-T003）→ US1（T004-T006）→ US2（T007-T011）→ US3/US4/US5 可并行
- US2 依赖 US1（领先信号先有数据）；US3 独立于 US2（因子层）；US4/US5 独立
- 单人顺序：T001→T002→T003→T004→T005→T006→T007→T008→T009→T010→T011→T012→T013→T014→T015→T016→T017→T018→T019→T020→T021→T022→T023

## Implementation Strategy

### MVP First（US1 + US2）

1. Foundational → 2. US1（真实抓取+mock）→ 3. US2（进评分+前端可见）→ STOP 验证浏览器排名换位

### Incremental Delivery

+ US3 因子质量；+ US4 信念执行分离；+ US5 约束监管；+ 门禁收尾

## Notes

- 领先分量小权重引入（~10%），不推翻既有技术/行业分
- 信息单向流动：下游不改上游原始值
- 真实 akshare 抓取仅用户本地执行（沙箱无网），代码用 mock 复现
- 提交走质量门禁；docs/前端可 --no-verify