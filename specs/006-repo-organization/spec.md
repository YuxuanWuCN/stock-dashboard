# Feature Specification: 仓库目录整理与密钥外置

**Feature Branch**: `006-repo-organization`

**Created**: 2026-08-17

**Status**: Draft

**Input**: User description: "整理文件，把不是项目主程序的代码放 2.0版 外面，环境的 .env 放外面，用 spec-kit"

## 背景 (Background)

**问题描述**：2.0版 仓库根目录与 tools/ 混入了大量"研究过程产出"（自荐报告 PDF、封箱检验 JSON/PNG/MD、历史总结 MD、一次性 PDF 生成脚本），与主程序（src/ + docs/ + 主流程 tools/）混在一起；同时真实密钥 `api-key.txt` 物理存放在 2.0版 根目录，虽然已被 .gitignore 忽略，但仍在项目目录内，存在误提交/误上传风险。

**规格写作前的侦察结论（2026-08-17 静态审阅）**：

1. **密钥现状**：`api-key.txt`（35 字节，DeepSeek key）位于 2.0版 根目录；`.gitignore` 已忽略 `api-key.txt`/`.env`/`*.key`；无真实 `.env` 文件，仅有 `.env.example`（git 跟踪，含 `DEEPSEEK_API_KEY_FILE=api-key.txt`）。
2. **密钥读取路径**：`src/llm/config.py` 第 16-19 行 `ROOT_PATH = Path(__file__).resolve().parents[2]`（= 2.0版 根），`DEEPSEEK_API_KEY_FILE = os.environ.get("DEEPSEEK_API_KEY_FILE", str(ROOT_PATH / "api-key.txt"))`。外置需改此默认路径，并保留环境变量覆盖。
3. **散落文件清单（2.0版 根目录）**：4 个自荐/研读 PDF、封箱检验产物（001258_*、MU_* 共约 12 个 JSON/PNG/MD）、`figures_test.png`、`report_figures/` 目录、历史总结 MD（CHANGELOG/FINAL_SUMMARY/STATUS/STRATEGY_EVOLUTION/WORK_SUMMARY 等 8 个）、`项目背书.md`。
4. **tools/ 一次性脚本**：PDF 生成器（generate_*_report_pdf.py、generate_issue_docx.py）、封箱/对比脚本（sealed_box_*.py、compare_trend_gate_*.py、verify_bet_types.py）。这些与研究产出同类，属"非主程序代码"。

**范围界定**：本 feature 做三件事——① 真实密钥 `api-key.txt` 外置到 2.0版 上一级目录并改 config 默认路径（含向后兼容回退）；② 把"研究过程产出"（PDF/封箱产物/历史总结/一次性脚本）迁移到 `D:\股票分析项目\research-outputs\`（2.0版 之外）；③ 更新 `.env.example` 与文档记录新路径约定。**不做**：不移动主程序（src/、docs/、tests/、config/、主流程 tools/）、不清理 .venv/.pytest_cache 等本地缓存（已在 gitignore）、不删除任何文件（仅迁移，保留历史）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 密钥外置且管线仍可读 (Priority: P1)

项目所有者要把真实密钥 `api-key.txt` 移出 2.0版 目录，同时保证 LLM 报告管线在无环境变量时仍能按新默认路径读到密钥，避免每日流水线因路径变更而静默退化。

**Why this priority**: 密钥安全优先；且密钥读取是每日流水线的地基，改动若破坏会直接导致 LLM 报告全部降级为模板，必须最先做并验证。

**Independent Test**: 运行一个独立脚本，断言 `DEEPSEEK_API_KEY_FILE` 解析到外置路径；在新路径放测试 key、旧路径无 key 时，LLMClient 读到新路径 key；新路径不存在时回退旧路径（迁移过渡期）。

**Acceptance Scenarios**:

1. **Given** `api-key.txt` 已移到 `D:\股票分析项目\api-key.txt` 且未设 `DEEPSEEK_API_KEY_FILE` 环境变量，**When** 调用 config 解析，**Then** 返回路径指向 2.0版 之外的 `api-key.txt`
2. **Given** 外置路径存在、旧路径（2.0版 内）不存在，**When** LLMClient 初始化，**Then** `_api_key_source == "file"` 且读到外置 key，非空
3. **Given** 外置路径不存在但旧路径仍存在（迁移中途），**When** 解析，**Then** 回退旧路径并记录 warning 日志（过渡期兼容，不报错）
4. **Given** 设置 `DEEPSEEK_API_KEY_FILE` 环境变量为任意路径，**When** 解析，**Then** 环境变量路径优先于所有默认路径

---

### User Story 2 - 研究产出迁移到 2.0版 之外 (Priority: P1)

项目所有者要把"研究过程产出"（自荐报告 PDF、封箱检验产物、历史总结 MD、一次性 PDF 生成脚本）从 2.0版 移到 `D:\股票分析项目\research-outputs\`，使 2.0版 根目录与 tools/ 只保留主程序相关文件。

**Why this priority**: 清理仓库是用户本次明确要求；根目录清爽后，后续融合（005）的 diff 才能干净可读，避免把研究垃圾混进功能提交。

**Independent Test**: 迁移后列出 2.0版 根目录与 tools/，断言已无目标文件（PDF/封箱产物/历史总结/一次性脚本），且迁移目标目录结构完整、文件可读（非删除）。

**Acceptance Scenarios**:

1. **Given** 2.0版 根目录的 4 个 PDF、封箱检验产物、`figures_test.png`、`report_figures/`、历史总结 MD、`项目背书.md`，**When** 执行迁移，**Then** 这些文件全部出现在 `research-outputs/` 对应子目录，且 2.0版 根目录不再含有它们
2. **Given** tools/ 里的一次性脚本（generate_*_report_pdf.py、generate_issue_docx.py、sealed_box_*.py、compare_trend_gate_*.py、verify_bet_types.py），**When** 执行迁移，**Then** 它们移入 `research-outputs/scripts/`，主流程 tools/（quality_gate.py、backfill_bet_types.py、run_quality.ps1、数据更新脚本）保持原位
3. **Given** 迁移完成，**When** 运行主流程测试（pytest 或导入主模块），**Then** 主程序不因迁移而 import 失败（迁移文件不被 src/ 或主流程引用）

---

### User Story 3 - 新路径约定文档化 (Priority: P2)

更新 `.env.example` 的注释与 README，明确 `api-key.txt`/`.env` 现在存放于 2.0版 之外，并说明 `DEEPSEEK_API_KEY_FILE` 的默认值与覆盖规则，供后续自己/协作者照做。

**Why this priority**: 文档化是安全约定的落地；避免未来自己或协作者又把密钥拷回项目内。

**Independent Test**: 检查 .env.example 中密钥路径说明已更新，README 中新增"密钥外置"小节。

**Acceptance Scenarios**:

1. **Given** .env.example，**When** 查看密钥相关注释，**Then** 明确写出"api-key.txt 位于 2.0版 上一级（项目外），勿放回仓库内"
2. **Given** README.md/README_CN.md，**When** 检索"密钥/API Key"，**Then** 存在外置路径与覆盖规则的说明段

---

### Edge Cases

- **外置目录不存在** → 回退旧路径（2.0版 内），并 warning 日志；绝不因找不到 key 而 crash（现有行为：无 key 时 LLM 报告降级模板）
- **新旧路径都无 key 文件** → 与现状一致：`_api_key_source` 非 "file"，报告降级模板生成
- **迁移目标目录已存在同名文件** → 不覆盖，跳过并记录；人工合并
- **研究产出被 src/ 意外引用** → 迁移前 grep 确认无 import；若有，先解耦再迁移
- **git 状态** → 迁移出 2.0版 的文件在 git 中显示为删除；迁移入 research-outputs/（仓库外）不入 git；需单独在提交说明中记录"迁移到仓库外"

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 系统 MUST 将 `api-key.txt` 的默认解析路径改为 2.0版 之外（`ROOT_PATH.parent / "api-key.txt"`），并保留 `DEEPSEEK_API_KEY_FILE` 环境变量最高优先级覆盖
- **FR-002**: 密钥解析 MUST 提供向后兼容回退：外置路径不存在且旧路径（2.0版 内）存在时，回退旧路径并记录 warning
- **FR-003**: 系统 MUST 在无任何可用 key 时保持现有降级行为（LLM 报告退化为模板生成，不 crash）
- **FR-004**: 迁移操作 MUST 只移动、不删除：所有"研究产出"文件移到 `D:\股票分析项目\research-outputs\` 下分类子目录，原内容逐字节保留
- **FR-005**: 迁移 MUST 不破坏主程序：迁移目标文件不得被 src/、tests/、config/ 或主流程 tools/ 引用；迁移后主模块可正常 import
- **FR-006**: 迁移 MUST 具备幂等性：重复执行跳过已迁移文件，不重复、不覆盖
- **FR-007**: `.env.example` 与 README MUST 更新密钥外置路径约定（FR-001 的新路径 + 环境变量覆盖规则）
- **FR-008**: 全部新增/修改代码 MUST 有 pytest 覆盖（密钥解析的正常/回退/缺失路径）

### Key Entities

- **SecretKeyResolver（新增/修订）**: 密钥文件路径解析逻辑；属性：候选路径列表（环境变量 → 外置默认 → 旧路径回退）、最终命中路径、命中来源（environment/file/none）
- **ProjectLayout（约定）**: 目录约定——主程序留在 2.0版；研究产出在 `research-outputs/`；密钥在 2.0版 上一级

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `api-key.txt` 不再存在于 2.0版 目录树内（`2.0版\api-key.txt` 不存在），而存在于 `D:\股票分析项目\api-key.txt`
- **SC-002**: 密钥解析测试覆盖 3 条路径（环境变量优先 / 外置默认 / 旧路径回退），全部通过
- **SC-003**: 2.0版 根目录不再含有：*.pdf（自荐/研读报告）、封箱检验产物（001258_*/MU_*）、figures_test.png、report_figures/、历史总结 MD
- **SC-004**: 迁移后 `pytest` 主流程用例（不含 2 个历史遗留失败）通过，无新增失败，证明主程序未被破坏
- **SC-005**: .env.example 与 README 含密钥外置说明，检索"密钥"命中新路径约定

## Assumptions

- **密钥外置目标路径**：`D:\股票分析项目\api-key.txt`（2.0版 的上一级目录），与 `参考项目\`、`archive\` 同级
- **研究产出目标路径**：`D:\股票分析项目\research-outputs\`，下设 `reports/`（PDF）、`sealed-box/`（封箱检验产物）、`summaries/`（历史总结 MD）、`scripts/`（一次性脚本）、`figures/`（散图）
- **"主程序"判定**：src/、docs/、tests/、config/、requirements.txt、pytest.ini、render.yaml、.github/、AGENTS.md、README*、start_local.*、watchlist.csv、strategy_pool.csv、.env.example、.quality-gates.json 均为主程序/项目基建，保留
- **主流程 tools/ 保留**：quality_gate.py、backfill_bet_types.py、run_quality.ps1、数据更新/排名生成脚本（被流水线调用）保留；仅迁移一次性研究脚本
- **不删除任何文件**：本 feature 只迁移位置，不删除内容
- **迁移不进 git 仓库**：research-outputs/ 位于 2.0版 git 仓库之外，由其自身（或未来独立归档）管理
