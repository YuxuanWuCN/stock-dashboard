# Tasks: Fama-MacBeth 多因子引擎（Phase 1）

**Input**: Design documents from specs/003-fama-macbeth-engine/（spec.md、plan.md、research.md、data-model.md、contracts/、quickstart.md）

**Prerequisites**: plan.md ✅、spec.md ✅、research.md ✅、data-model.md ✅、contracts/ ✅、quickstart.md ✅

**Tests**: 必含（spec SC-004 与蓝图 KPI 明确要求 100% 覆盖率；AGENTS.md 强制测试先行）。测试任务一律"先写、先看到失败，再实现"。

**Organization**: 按用户故事分组（US1 因子数据层 P1 → US2 两阶段回归 P1 → US3 门控接入 P2 → US4 质量门禁 P3），每个故事独立可测、独立交付。

## Format: ID [P?] [Story?] 带文件路径的描述

- [P]：可并行（不同文件、无未完成依赖）
- [Story]：所属用户故事（US1/US2/US3/US4）

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: 依赖与参数基础设施

- [X] T001 安装依赖：.venv\Scripts\pip install statsmodels（自动带 scipy/patsy），并把 statsmodels 写入 requirements.txt（research.md R1）
- [X] T002 [P] 在 src/analysis/config.py 扩展回归与门控参数：ALPHA_P_THRESHOLD=0.05、IR_THRESHOLD=0.3、FACTOR_WINDOW_YEARS=5、MIN_OBS_DAYS=250、RF_ANNUAL_DEFAULT=0.025、GAP_RATE_MAX=0.05、HAC_MAXLAGS=5、FACTOR_DB_PATH（默认 docs/data/factors/factors.db）
- [X] T003 [P] 创建 docs/data/factors/ 目录与 5 年日频合成因子夹具 docs/data/factors/fixture_factors.csv（表头 date,MKT,SMB,HML,MOM,rf；约 1250 行；含 5% 以内可控缺口）

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: 所有故事共用的测试基础设施（必须先于任何故事）

**⚠️ CRITICAL**: 用户故事开始前必须完成本阶段

- [X] T004 在 tests/test_fama_macbeth.py 中实现合成数据生成器（synthetic_factors / synthetic_stock_returns：给定 beta 生成 4 因子载荷的收益序列，支持注入已知 alpha 与残差波动率），供 US1–US4 全部测试复用

**Checkpoint**: 基础就绪——可开始用户故事实现

---

## Phase 3: User Story 1 - 因子数据层：可审计的日频 4 因子库 (Priority: P1) 🎯 MVP

**Goal**: CSV 契约校验 + SQLite 因子库 + 对齐与数据质量报告；回答"数据从哪来、缺了哪些日期、有无未来数据"

**Independent Test**: 仅用 fixture_factors.csv 离线验证：导入 → 完整性/对齐性/无前视断言 → 质量报告输出（spec US1 Independent Test）

### Tests for User Story 1（先写，先看到失败）

- [X] T005 [P] [US1] 在 tests/test_fama_macbeth.py 写 CSV 契约校验测试：缺失列报错、重复日期报错、缺口率>5% 报错、乱序排序+告警、区间不足报错（FR-001，契约 contracts/factors-csv.md）
- [X] T006 [P] [US1] 在 tests/test_fama_macbeth.py 写 SQLite 入库与查询测试：UPSERT 幂等重导入、事务回滚不留半写、区间查询正确、无重复日期（FR-002/FR-003）
- [X] T007 [P] [US1] 在 tests/test_fama_macbeth.py 写对齐与质量报告测试：因子∩K线交集策略、剔除日期记录、质量报告字段完整（FR-003/FR-012）

### Implementation for User Story 1

- [X] T008 [US1] 在 src/analysis/factor_db.py 实现 CSV 契约校验器 validate_factors_csv（表头/列序、重复日期、缺口率、乱序、覆盖区间，按 contracts/factors-csv.md 校验规则逐条实现）
- [X] T009 [US1] 在 src/analysis/factor_db.py 实现 SQLite 入库与查询（factors/source_meta 表结构按 data-model.md；import_to_db 幂等 UPSERT + 事务；query_range 按日期区间）
- [X] T010 [US1] 在 src/analysis/factor_db.py 实现对齐与质量报告（align_with_kline 交集策略 + 剔除记录；write_quality_report 输出 docs/data/factors/quality_report.json）
- [X] T011 [US1] 在 src/analysis/factor_db.py 提供 CLI 入口：python -m src.analysis.factor_db import --csv <path>（quickstart.md 用法一致）

**Checkpoint**: US1 独立可用——离线夹具即可入库、质检、审计

---

## Phase 4: User Story 2 - Fama-MacBeth 两阶段回归 (Priority: P1)

**Goal**: 阶段一时间序列回归输出 alpha/p/IR/betas/VIF；阶段二横截面 FM 信息性输出；合成样本还原、纯因子暴露识别、数据不足 null

**Independent Test**: 注入 alpha=0.5%/日 的合成序列还原误差 ±20% 且判 True Alpha；alpha=0 序列判 reject；<250 日输出 null+原因（spec US2）

### Tests for User Story 2（先写，先看到失败）

- [X] T012 [P] [US2] 在 tests/test_fama_macbeth.py 写还原测试：注入 alpha=0.5%/日、IR≈0.5 的合成序列，断言估计 alpha 误差 ±20% 内、p<0.05、IR>=0.3（US2 验收 1）
- [X] T013 [P] [US2] 在 tests/test_fama_macbeth.py 写纯因子暴露与数据不足测试：alpha=0 纯 MKT 暴露 → p>=0.05 或 IR<0.3；样本 <250 日 → 输出 null + 原因（US2 验收 2/4，FR-009）
- [X] T014 [P] [US2] 在 tests/test_fama_macbeth.py 写泄漏注入测试：用未来因子值污染回归输入 → 断言必须触发失败（FR-008、SC-004）

### Implementation for User Story 2

- [X] T015 [US2] 在 src/analysis/fama_macbeth.py 实现阶段一时间序列回归（statsmodels OLS，cov_type=HAC、maxlags 取 config；输出 alpha/alpha_p_value/information_ratio/betas/vif/n_obs/converged；数据不足输出 null+reason，结构按 data-model.md RegressionResult）
- [X] T016 [US2] 在 src/analysis/fama_macbeth.py 实现阶段二横截面 FM（每日截面收益对阶段一 beta 回归 → lambda_t 时间均值与 std/sqrt(T) 标准误，信息性输出入报告）
- [X] T017 [US2] 在 src/analysis/fama_macbeth.py 实现全池批量入口 run_all（202 只循环，实测 <15 分钟预算 SC-005）与 CLI 调试入口 python -m src.analysis.fama_macbeth --code 600519

**Checkpoint**: US1+US2 可用——任何标的可离线输出回归结果与显著性判定

---

## Phase 5: User Story 3 - Alpha 门控接入排行榜 (Priority: P2)

**Goal**: 只有 True Alpha（p<0.05 且 IR>=0.3）进激进组合候选；reject 降级 Watchlist 记录原因；ranking.json/{code}.json 带 alpha_gate 字段且过 schema 校验

**Independent Test**: mock 行情跑 build_ranking 全流水线，断言候选=原候选∩pass、字段完整（spec US3）

### Tests for User Story 3（先写，先看到失败）

- [X] T018 [P] [US3] 在 tests/test_fama_macbeth_integration.py 写集成测试：mock 行情跑 build_ranking 流水线，断言激进候选只含 alpha_gate=pass、ranking.json 与 {code}.json 字段完整（US3 验收 1，契约 contracts/alpha-gate-output.md）
- [X] T019 [P] [US3] 在 tests/test_fama_macbeth_integration.py 写降级测试：全池 reject → 按原机会分回退补齐 + 告警标注、不产生空组合不崩溃（US3 验收 2，FR-011）

### Implementation for User Story 3

- [X] T020 [US3] 在 src/analysis/alpha_gate.py 实现门控判定 evaluate_gate（verdict=pass/reject + reject_reason 枚举 statistical/economical/insufficient_data，阈值取 config）
- [X] T021 [US3] 在 src/build_ranking.py 插入门控调用点（机会分计算之后、激进组合候选构建之前），每标的输出 alpha_gate 字段组并写入 ranking.json/{code}.json
- [X] T022 [US3] 在 src/analysis/schema.py 扩展 alpha_gate 字段校验（reject 必填 reject_reason；insufficient_data 时 alpha/p/IR/betas 全 null；旧字段保持兼容）
- [X] T023 [US3] 在 src/build_ranking.py 实现降级策略（通过数 < 激进组合 min_size=5 时按原机会分回退补齐并记录告警标注）

**Checkpoint**: 排行榜具备风险调整后的 Alpha 门控，US1–US3 全部独立可用

---

## Phase 6: User Story 4 - 质量门禁与独立复核 (Priority: P3)

**Goal**: 新模块 100% 覆盖率、泄漏注入必失败验证、独立手算复核 3 只、门禁三级全绿

**Independent Test**: small → medium → heavy 门禁全绿；手算复核与模块输出一致（spec US4）

- [X] T024 [P] [US4] 在 .quality-gates.json 把 tests/test_fama_macbeth.py 注册进 small 批次、tests/test_fama_macbeth_integration.py 注册进 medium 批次（保持现有批次其余条目不动）
- [X] T025 [P] [US4] 覆盖率核对：新模块 src/analysis/factor_db.py、fama_macbeth.py、alpha_gate.py 行覆盖 100%（SC-004），不足则补测试
- [X] T026 [P] [US4] 独立手算复核 3 只小样本（alpha/p/IR 用可手算数据核对）并归档记录到 reports/ 下（SC-006）
- [X] T027 [US4] 按 AGENTS.md 走完整门禁：tools/run_quality.ps1 begin-unit（写明验收标准）→ small → medium → heavy 全绿（含泄漏注入测试必须能触发失败的验证）

**Checkpoint**: 全部故事完成且通过项目质量门禁，可发布提交

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 收尾与跨故事改进

- [X] T028 [P] 验证 quickstart.md 全流程可复现（离线部分已验证：空库→CLI 导入 1250 行→CLI 回归 600519 诚实输出 insufficient_data→质量报告；build_ranking 全量联网运行留待每日流水线验证，门控输出路径已由 53 项离线测试覆盖）
- [X] T029 [P] （可选）docs/index.html 前端展示：本 feature 跳过（spec 标注非必需，前端展示留待 Phase 4 校准后统一设计）
- [X] T030 代码清理与最终审阅：新模块 docstring 齐全、无调试残留；临时脚本已清理；plan.md 源码结构与实际一致（factor_db/fama_macbeth/alpha_gate + 两个测试文件 + .quality-gates.json + requirements.txt）

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: 无依赖，立即开始
- **Foundational (Phase 2)**: 依赖 Phase 1 完成——阻塞所有用户故事
- **User Stories (Phase 3+)**: 依赖 Foundational 完成；本 feature 故事间有天然数据链：US2 依赖 US1（需对齐后的因子序列）、US3 依赖 US2（需 RegressionResult）、US4 依赖 US1–US3（门禁注册需全部测试就绪）。单人开发按 P1 → P1 → P2 → P3 顺序执行
- **Polish (Phase 7)**: 依赖全部故事完成

### User Story Dependencies

- **US1 (P1)**: Foundational 后即可开始，无其他依赖
- **US2 (P1)**: 依赖 US1（对齐与质量报告接口），但可独立测试（直接用合成因子序列）
- **US3 (P2)**: 依赖 US2（门控消费 RegressionResult），可独立测试（mock 回归结果）
- **US4 (P3)**: 依赖 US1–US3 全部完成

### Within Each User Story

- 测试必须先行且先看到失败，再实现
- 测试组内 [P] 任务可并行（T005–T007、T012–T014、T018–T019）
- 实现按数据流顺序：校验器 → 存储 → 对齐；回归 → 横截面 → 批量；判定 → 接入 → schema → 降级
- 故事完成并独立验证后再进入下一故事

### Parallel Opportunities

- Phase 1：T002 与 T003 并行
- US1 测试：T005/T006/T007 并行；US2 测试：T012/T013/T014 并行；US3 测试：T018/T019 并行
- US4：T024/T025/T026 并行（T027 收口）
- 若多人协作：Foundational 后 US1 与 US2 的测试任务可并行起草（实现仍需按数据链顺序）

---

## Parallel Example: User Story 1

    # 同时起草 US1 的三个测试（不同断言域，无冲突）：
    Task: "CSV 契约校验测试（T005）在 tests/test_fama_macbeth.py"
    Task: "SQLite 入库与查询测试（T006）在 tests/test_fama_macbeth.py"
    Task: "对齐与质量报告测试（T007）在 tests/test_fama_macbeth.py"
    # 全部失败后，再按 T008 → T009 → T010 → T011 顺序实现

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. 完成 Phase 1 Setup
2. 完成 Phase 2 Foundational（CRITICAL - 阻塞全部故事）
3. 完成 Phase 3 US1
4. **STOP and VALIDATE**：夹具入库 → 质检报告 → 独立演示"可审计因子库"
5. 交付/演示 MVP

### Incremental Delivery

1. Setup + Foundational → 基础就绪
2. + US1 → 独立测试 → 交付（MVP：因子库与质检）
3. + US2 → 独立测试 → 交付（可离线输出 alpha/p/IR 的回归引擎）
4. + US3 → 独立测试 → 交付（排行榜具备 Alpha 门控）
5. + US4 → 门禁全绿 → 可发布提交

### Parallel Team Strategy（若多人）

1. 团队共同完成 Setup + Foundational
2. Foundational 后：A 负责 US1 测试起草，B 负责 US2 测试起草（实现顺序仍受数据链约束）
3. 故事依次集成，各自独立验证

---

## Notes

- [P] 任务 = 不同文件、无未完成依赖
- [USx] 标签映射到 spec.md 用户故事，便于追溯
- 每个故事独立可完成、可测试
- 验证测试先失败再实现
- 每完成一个任务或逻辑组即提交（docs 类提交沿用本 feature 已批准的 --no-verify 策略；源码提交必须走质量门禁）
- 任一 Checkpoint 可停下独立验证故事
- 避免：模糊任务、同文件冲突、破坏故事独立性的跨故事依赖
