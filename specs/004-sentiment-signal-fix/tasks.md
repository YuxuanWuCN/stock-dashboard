# Tasks: LLM 情绪信号度量与数据口径修复（Phase 0）

**Input**: specs/004-sentiment-signal-fix/（spec.md、plan.md、research.md、data-model.md、quickstart.md）

**Tests**: 必含（SC-004 100% 覆盖；AGENTS.md 测试先行）。测试任务先写、先看到失败，再实现。

## Format: ID [P?] [Story?] 带文件路径的描述

---

## Phase 1: Setup

**Purpose**: 本 feature 无新依赖（Wilson 手写、零网络），Setup 为空。

---

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T001 在 src/market_feedback.py 新增 realized_return(close_series, t_index, horizon)：ret_N = (close[t+N] − close[t]) / close[t] × 100，窗口不足返回 None（口径见 research.md R2）
- [X] T002 在 tests/test_market_feedback_realized.py 建立夹具工具：合成 close 序列、构造样本集（含无分/中性/一致/不一致四类）、tmp 反馈文件写入器

**Checkpoint**: 基础就绪

---

## Phase 3: User Story 1 - 离线诊断报告 (Priority: P1) 🎯 MVP

**Goal**: 可复现回答"34.7% 到底度量了什么"：ret 来源审计 + 分母构成 + 真实方向统计（Wilson CI vs 50%）

**Independent Test**: tmp 夹具数据跑诊断脚本，断言报告含三段内容且结论三选一

### Tests for User Story 1（先写，先看到失败）

- [X] T003 [P] [US1] 在 tests/test_market_feedback_realized.py 写诊断脚本测试：夹具样本（ret 为预测值特征 + 无分/中性混合）→ 报告含根因审计段/分母构成段/真实方向统计段（先失败：脚本不存在）

### Implementation for User Story 1

- [X] T004 [US1] 在 tools/diagnose_sentiment_alignment.py 实现离线诊断（读 docs/data/llm/market_feedback.json + docs/data/kline/*.json；三段报告；Wilson 95% CI；结论三选一 正相关/无关/反转）
- [X] T005 [US1] 运行真实数据诊断并把报告归档 reports/sentiment_signal_diagnosis.md（覆盖式）

**Checkpoint**: 诊断结论可见

---

## Phase 4: User Story 2 - 数据口径修复 (Priority: P1)

**Goal**: record_event 只记录真实已实现收益；预测值独立保存；历史样本幂等回填

**Independent Test**: 合成 K 线 + 已知未来收益手算对照；回填两次运行逐字节一致

### Tests for User Story 2（先写，先看到失败）

- [X] T006 [P] [US2] 在 tests/test_market_feedback_realized.py 写 record_event 契约测试：传入 KNN 预测值 → 断言预测值只落 forecast 字段、ret 字段为真实收益；无真实收益 → None（先失败：现契约接受预测值）
- [X] T007 [P] [US2] 在 tests/test_market_feedback_realized.py 写回填测试：tmp 数据 → 快照只建一次、两次运行逐字节一致、不可算样本显式标注（先失败：脚本不存在）

### Implementation for User Story 2

- [X] T008 [US2] 在 src/market_feedback.py 修改 record_event：ret_3d/ret_5d 参数只接受真实收益；样本新增 realized_ret_3d_pct/realized_ret_5d_pct/forecast_ret_5d_pct/realized_available 字段（data-model.md）
- [X] T009 [US2] 在 src/llm/generate_reports.py 修改 _record_market_feedback：从 docs/data/kline/{code}.json 用 realized_return 计算真实收益传入；KNN 预测值存 forecast_ret_5d_pct；K 线缺失/窗口不足 → None + 标注
- [X] T010 [US2] 在 tools/backfill_market_feedback.py 实现回填：首次运行先快照（market_feedback.backup_YYYYMMDD.json）→ 逐样本重算 realized_ret → 原子写回 + 前后对比统计；幂等
- [X] T011 [US2] 对真实数据运行回填并核验对比报告

**Checkpoint**: 反馈样本的收益字段可信

---

## Phase 5: User Story 3 - 度量口径修复 (Priority: P2)

**Goal**: compute_summary 新增 directional_accuracy（决定性样本口径），旧字段保留

**Independent Test**: 构造样本集手算（10 条：3 无分/2 中性/3 一致/2 不一致 → 0.6；决定性 0 → None）

### Tests for User Story 3（先写，先看到失败）

- [X] T012 [P] [US3] 在 tests/test_market_feedback_realized.py 写 compute_summary 手算测试：构造样本 → directional_accuracy == 3/5 == 0.6；决定性样本 0 → None；旧 alignment_rate 仍输出（先失败：字段不存在）

### Implementation for User Story 3

- [X] T013 [US3] 在 src/market_feedback.py 实现 compute_summary 扩展：directional_accuracy、decisive_sample_count、no_score_sample_count（|score|>=0.1 且有真实收益为决定性样本；除零 → None）

**Checkpoint**: 校准报告可读正确指标

---

## Phase 6: User Story 4 - 验证与门禁 (Priority: P3)

**Goal**: 回填后真实数据重算 + 与 50% 基线对比入档；三级门禁全绿

- [X] T014 [P] [US4] 在 tests/test_market_feedback_realized.py 写泄漏注入测试：用 event_date 之前的 K 线数据计算收益 → 断言必须触发失败（FR-007）
- [X] T015 [US4] 用回填后的真实数据重算 directional_accuracy + Wilson 95% CI，与 50% 基线对比，结论并入 reports/sentiment_signal_diagnosis.md（样本 < 30 标注功效不足）
- [X] T016 [US4] 覆盖率核对（新增代码 100%）+ 按 AGENTS.md 走 begin-unit → small → medium → heavy 全绿

**Checkpoint**: 全部故事完成且通过质量门禁

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 清理临时文件、核对 quickstart.md 命令与实现一致、更新 tasks.md 勾选并最终提交

---

## Dependencies & Execution Order

- Foundational → 全部故事；US2 依赖 US1 的诊断结论（决定是否含映射修复分支），US3 依赖 US2（新字段口径），US4 依赖 US1–US3
- 故事内测试先行；T003/T006/T007/T012/T014 可并行起草
- 单人顺序：T001→T002→T003→T004→T005→T006→T007→T008→T009→T010→T011→T012→T013→T014→T015→T016→T017

## Implementation Strategy

### MVP First（US1）

1. Foundational（T001-T002）→ 2. US1（T003-T005）→ 3. STOP 并验证诊断结论

### Incremental Delivery

+ US2 → 数据可信；+ US3 → 指标可信；+ US4 → 结论入档 + 门禁全绿

## Notes

- 若 US1 诊断结论为"信号真反转"，在 US2/US3 之间插入映射修复任务（spec US3 条件分支）；否则不修改映射
- 原始 K 线只读；market_feedback.json 为派生数据可回填（先快照）
- 提交沿用项目惯例：源码提交走质量门禁；docs 提交可 --no-verify（已获用户批准）