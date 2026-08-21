# Tasks: 仓库目录整理与密钥外置

**Input**: /specs/006-repo-organization/（spec.md、plan.md）

**Tests**: 必含（FR-008 密钥解析 4 路径；AGENTS.md 测试先行）

## Format: ID [P?] [Story?] 带文件路径的描述

---

## Phase 1: Setup

- [X] T001 运行 `tools/run_quality.ps1 begin-unit` 记录基线（源码改动前的质量门禁起点）

## Phase 2: Foundational (Blocking Prerequisites)

- [X] T002 在 tests/ 新增密钥解析测试夹具：临时目录模拟外置/旧路径/environment 变量四种场景

**Checkpoint**: 测试骨架就绪

---

## Phase 3: User Story 1 - 密钥外置 (Priority: P1) 🎯 MVP

**Goal**: api-key.txt 移出 2.0版；config.py 默认路径指向外置；LLMClient 仍能读到 key

**Independent Test**: 独立脚本断言外置路径存在、旧路径不存在、LLMClient._api_key_source=="file"

### Tests for US1（先写，先失败）

- [X] T003 [P] [US1] 在 tests/test_secret_key_resolver.py 写解析测试：环境变量优先 / 外置默认命中 / 旧路径回退 / 双缺失 → 非 file（先失败：现 config 默认指向 2.0版 内）

### Implementation for US1

- [X] T004 [US1] 在 src/llm/config.py 改 DEEPSEEK_API_KEY_FILE 默认值为 ROOT_PATH.parent / "api-key.txt"，并新增候选路径回退逻辑（外置不存在→旧路径 + warning）
- [X] T005 [US1] 物理迁移：Move api-key.txt → D:\股票分析项目\api-key.txt（2.0版 之外）
- [X] T006 [US1] 独立验证：运行断言脚本确认新路径命中、LLMClient 读到 key、旧路径不存在

**Checkpoint**: 密钥外置且管线可读

---

## Phase 4: User Story 2 - 研究产出迁移 (Priority: P1)

**Goal**: 非主程序产出全部移到 research-outputs/；2.0版 根目录与 tools/ 清爽；主程序不破坏

**Independent Test**: 迁移后列出 2.0版 根目录与 tools/ 断言无目标文件；pytest 主流程无新增失败

### Tests for US2

- [X] T007 [P] [US2] 迁移前 grep 确认目标文件不被 src/、tests/、config/、主流程 tools/ import（若有则先解耦）

### Implementation for US2

- [X] T008 [US2] 迁移 2.0版 根目录产出：4 PDF → research-outputs/reports/；封箱产物 → sealed-box/；历史总结 MD + 项目背书.md → summaries/；figures_test.png + report_figures/ → figures/
- [X] T009 [US2] 迁移 tools/ 一次性脚本：generate_*_report_pdf.py、generate_issue_docx.py、sealed_box_*.py、compare_trend_gate_*.py、verify_bet_types.py → research-outputs/scripts/
- [X] T010 [US2] 运行 pytest 主流程（排除 2 个历史遗留失败）确认无新增失败

**Checkpoint**: 仓库清爽、主程序未破坏

---

## Phase 5: User Story 3 - 路径约定文档化 (Priority: P2)

- [X] T011 [US3] 更新 .env.example 密钥注释：api-key.txt 位于 2.0版 上一级（项目外）
- [X] T012 [US3] 更新 README.md / README_CN.md 新增"密钥外置"说明段

---

## Phase 6: Polish & Cross-Cutting

- [X] T013 运行质量门禁 small→medium→heavy（密钥解析相关用例全绿）
- [X] T014 提交：源码改动走质量门禁；迁移文件在 git 中显示删除，提交说明记录"迁移到仓库外 research-outputs/"

---

## Dependencies & Execution Order

- Foundational（T002）→ US1（T003-T006）；US2（T007-T010）与 US1 无依赖可并行；US3 依赖 US1
- 单人顺序：T001→T002→T003→T004→T005→T006→T007→T008→T009→T010→T011→T012→T013→T014

## Implementation Strategy

### MVP First（US1）

1. Foundational → 2. US1（密钥外置）→ 3. STOP 验证管线可读

### Incremental Delivery

+ US2 → 仓库清爽；+ US3 → 约定文档化；+ 门禁 → 收尾

## Notes

- 迁移只移动不删除；research-outputs/ 在 git 仓库之外
- 密钥解析改动是唯一源码变更，严格走 begin-unit 质量门禁
- 提交沿用项目惯例：源码提交走门禁；纯迁移/docs 提交可 --no-verify（已获用户批准）