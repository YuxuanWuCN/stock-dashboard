# 任务：020-all-in-one-multi-asset-synthesis
# Rainbow-FinGPT v4.0 全域多资产因果量化投研中台任务清单 (Multi-Asset Synthesis Tasks)

**输入**：来自 `specs/020-all-in-one-multi-asset-synthesis/` 的设计文档  
**先决条件**：`plan.md`（必需）、`spec.md`（必需）、`research.md`、`data-model.md`、`contracts/`、`quickstart.md`  

**组织方式**：任务严格按用户故事（US1、US2、US3）分阶段组织，每个故事具备独立实现、独立验证与增量交付能力。

---

## 阶段 1：设置（共享基础设施与项目初始化）

**目的**：搭建多资产 Monorepo 分层骨架，确立空间纪律与依赖基础。

- [X] T001 根据实现计划创建多资产目录结构（`competitions/`、`src/core/math/`、`src/assets/equity/`、`src/assets/commodity/`、`src/assets/wealth/`、`src/intelligence/`、`tests/core/`、`tests/equity/`、`tests/commodity/`、`tests/integration/`）
- [X] T002 [P] 在 `.gitignore` 中配置极星运行时缓存、临时中间数据与产物过滤规则，严格执行《零根目录污染》
- [X] T003 [P] 在 `requirements.txt` 中统一并固化数据科学与 Web 依赖（`pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`, `flask`, `flask-cors`, `pytest`）

---

## 阶段 2：基础（阻塞先决条件：底层共享数学内核）

**目的**：提供所有资产轨道（权益、商品、财富）共享的高精度计量与统计检验基础设施。

**⚠️ 关键**：本阶段完成后，底层核心算法将具备确定性数学保障，各资产赛道方可并行推进。

- [X] T004 在 `src/core/math/fama_macbeth.py` 中实现统一 Fama-MacBeth 2-Stage 横截面回归与 Newey-West HAC 异方差自相关稳健标准误计算（$q = \max(1, \lfloor 4(T/100)^{2/9} \rfloor)$）
- [X] T005 [P] 在 `src/core/math/orthogonalization.py` 中实现 Gram-Schmidt 因子正交化与 PCA 降维算子
- [X] T006 [P] 在 `src/core/math/alpha_gate.py` 中实现双重门禁（$p < 0.05$ 且 $IR \ge 0.30$）及除零安全保护
- [X] T007 在 `tests/core/test_fama_macbeth.py` 中编写已知解析解的小样本数值对齐单元测试

**检查点**：基础就绪，`pytest tests/core/` 必须全绿通过。

---

## 阶段 3：用户故事 1 - 跨赛道评审材料与申报体系物理隔离 (优先级: P0) 🎯 MVP

**目标**：将大创赛与郑商所杯的申报材料、路演文稿与评审手册进行物理隔离与归拢，杜绝赛道串味，满足双赛道独立评审诉求。  
**独立测试**：运行隔离性契约测试，断言大创赛目录不含期货商品杂质、郑商所目录不含 A 股产业申报，且根目录无散落申报文件。

### 用户故事 1 的测试
- [X] T008 [P] [US1] 在 `tests/integration/test_competition_isolation.py` 中编写赛事材料隔离性契约测试

### 用户故事 1 的实现
- [X] T009 [P] [US1] 从 `origin/contest-2026` 提取大创赛全套材料至 `competitions/dachuang_2026/`（包含产业申报书 md/docx/pdf、18页金牌路演PPT逐页演讲文稿、评委答辩专家攻防QA靶向演练手册、达观数据答卷方案）
- [X] T010 [P] [US1] 从 `origin/v3.1` 提取郑商所杯材料至 `competitions/czce_futures/`（包含 01_研究计划与论文、02_极星量化与实盘、03_算法模型与回测）
- [X] T011 [US1] 清理主工作区根目录下散落的旧版 PPT 与答卷文本至对应 `competitions/` 目录，达成根目录高洁净度

**检查点**：此时 MVP 达成！赛事申报与答辩路演材料已实现完全物理隔离与独立查阅。

---

## 阶段 4：用户故事 2 - 核心计算引擎与多资产领域流水线解耦 (优先级: P0)

**目标**：将因果推理引擎（ADR-0001/0002、Serenity Chokepoint）、A 股权益赛道（202 股票池、存储超级周期、黄金杠铃、CSMAR 评测）与大宗商品赛道（纯碱/玻璃 TES、极星 19.5 插件、仓单）分层解耦归拢。  
**独立测试**：分别运行 `pytest tests/equity/` 与 `pytest tests/commodity/`，两大赛道测试集均能独立通过、零相互干扰。

### 用户故事 2 的测试
- [X] T020 [P] [US2] 在 `tests/equity/test_equity_pipeline.py` 中建立 A 股 202 标的与因子回归流水线测试
- [X] T021 [P] [US2] 在 `tests/commodity/test_tes_and_collar.py` 中建立郑商所商品期现套保与领子对冲测试（纳管 v3.1 既有用例）

### 用户故事 2 的实现
- [X] T012 [P] [US2] 在 `src/intelligence/two_layer_engine.py` 中实现 ADR-0001 两层解耦引擎（强制 `[FACT]` 标签与代码门禁一票否决）
- [X] T013 [P] [US2] 在 `src/intelligence/causal_ontology.py` 中实现 ADR-0002 产业链物理工艺本体（4 层节点拓扑与化学计量比 $k=0.20$）
- [X] T014 [P] [US2] 在 `src/intelligence/chokepoint/chokepoint_analyzer.py` 中封装 `serenity-chokepoint-investing-enhanced` 供应链卡脖子瓶颈拓扑分析引擎
- [X] T015 [P] [US2] 在 `src/assets/equity/storage_runner.py` 中封装 A 股 202 核心池、存储芯片超级周期与黄金杠铃回测流水线
- [X] T016 [P] [US2] 在 `src/assets/commodity/tes_pipeline.py` 中封装纯碱/玻璃跨资产期望盈余 (TES) 动态套保与注册仓单跟踪流水线
- [X] T017 [P] [US2] 在 `src/assets/commodity/polarstar_plugin/` 中封装极星 19.5 原生量化插件（CZCE_19_5_DualProduct_Plugin）
- [X] T018 [P] [US2] 在 `src/assets/wealth/silver_allocation.py` 中封装银发安心大类资产配置算法
- [X] T019 [US2] 在 `src/server.py` 中根据 `contracts/multi-asset-api.json` 实现统一 OpenAPI 多资产数据网关

**检查点**：多资产计算与因果推断流水线实现完全解耦，双赛道测试全绿。

---

## 阶段 5：用户故事 3 - 统一多模全景交互中台与离线容灾 (优先级: P1)

**目标**：打通统一 Web 交互中台，支持银发普惠、A 股量化研报、郑商所期现套保、产业链因果拓扑四维一键穿透，并保证 100% 离线单文件秒开容灾。  
**独立测试**：在无网络环境下打开离线 HTML，所有图表与快照数据完整呈现，无控制台致命报错。

### 用户故事 3 的测试
- [X] T025 [P] [US3] 在 `tests/integration/test_multi_asset_synthesis.py` 中编写端到端多资产 Web 快照契约与离线加载测试

### 用户故事 3 的实现
- [X] T022 [P] [US3] 在 `docs/index_commodity.html` 中实现郑商所纯碱/玻璃跨资产期现双轨套保与注册仓单交互面板
- [X] T023 [US3] 在 `docs/index.html` 与 `docs/index_wealth.html` 顶部增加全局模式切换导航栏（Tab Bar），实现四维场景毫秒级穿透
- [X] T024 [US3] 在 `docs/data/` 目录组织同步完整离线同构学术快照（`ranking_cross_asset.json`, `performance.json`, `market_temperature.json`），实现零外部 CDN 依赖

**检查点**：Web 交互终端全景打通，赛场弱网/断网环境下秒级自愈。

---

## 阶段 6：完善与跨领域关注点 (Polish & Cross-Cutting)

**目的**：全景文档定稿、质量门禁巡检与工程交接。

- [X] T026 重构主根目录 `README.md`，更新 Rainbow-FinGPT v4.0 全域多资产投研中台全景架构图与赛道指引
- [X] T027 [P] 执行全量分层测试矩阵（`pytest tests/core tests/equity tests/commodity tests/integration`），确保 100% 绿色通过
- [X] T028 运行 `tools/run_quality.ps1` 质量门禁，输出最终合并验收报告与审计记录

---

## 依赖关系与用户故事执行顺序

```mermaid
graph TD
    subgraph Setup & Foundation
        T001[T001 目录架构] --> T004[T004 Fama-MacBeth 核心]
        T002[T002 空间与忽略配置] --> T004
        T003[T003 依赖统一] --> T004
        T004 --> T005[T005 正交化]
        T004 --> T006[T006 代码门禁]
        T004 --> T007[T007 基础测试]
    end

    subgraph US1 [US1 赛事材料隔离 (MVP)]
        T007 --> T008[T008 隔离测试]
        T008 --> T009[T009 大创赛材料归拢]
        T008 --> T010[T010 郑商所材料归拢]
        T009 --> T011[T011 根目录清洗]
        T010 --> T011
    end

    subgraph US2 [US2 算法与资产流水线解耦]
        T007 --> T012[T012 两层解耦]
        T007 --> T013[T013 因果本体]
        T007 --> T014[T014 Chokepoint 拓扑]
        T012 --> T015[T015 A 股权益流水线]
        T013 --> T016[T016 商品 TES 流水线]
        T016 --> T017[T017 极星插件]
        T007 --> T018[T018 银发配置]
        T015 --> T019[T019 统一网关]
        T016 --> T019
        T019 --> T020[T020 权益测试]
        T019 --> T021[T021 商品测试]
    end

    subgraph US3 [US3 统一交互中台与离线容灾]
        T019 --> T022[T022 郑商所交互面板]
        T019 --> T023[T023 导航栏穿透打通]
        T022 --> T024[T024 离线快照同步]
        T023 --> T024
        T024 --> T025[T025 集成契约测试]
    end

    subgraph Polish [完善与门禁]
        T011 --> T026[T026 README 重构]
        T020 --> T026
        T021 --> T026
        T025 --> T026
        T026 --> T027[T027 全量测试执行]
        T027 --> T028[T028 质量门禁归档]
    end
```

---

## 并行执行机会 (Parallel Opportunities)

- **阶段 1 与阶段 2**：`T002` 与 `T003` 可并行执行；`T005` 与 `T006` 可在 `T004` 框架确立后并行执行。
- **阶段 3 (US1)**：`T008`、`T009`、`T010` 面向完全独立的文件系统目录，可 100% 并行提取。
- **阶段 4 (US2)**：`T012`（两层解耦）、`T013`（因果本体）、`T014`（Chokepoint）、`T015`（权益）、`T016`（商品）、`T018`（财富）互不干扰，支持全面并行开发。
- **阶段 5 (US3)**：`T022` 与 `T025` 可并行推进。

---

## 增量实施策略 (Implementation Strategy)

1. **MVP 阶段（阶段 1 + 2 + 3）**：
   - 优先交付 `competitions/dachuang_2026/` 与 `competitions/czce_futures/` 的物理隔离，确保无论当前面临大创赛申报还是郑商所杯评审，文档资产均立即处于 100% 安全就绪状态。
2. **Core 阶段（阶段 4）**：
   - 提取共享数学底座与因果图谱引擎，解耦运行 A 股与商品回测，实现双赛道代码自洽。
3. **Full System 阶段（阶段 5 + 6）**：
   - 统一 Web 终端与全局路由导航，执行全量自动化门禁与 README 换代。
