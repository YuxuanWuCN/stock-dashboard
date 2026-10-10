# 功能规格：020-all-in-one-multi-asset-synthesis
# Rainbow-FinGPT v4.0 全域多资产因果量化投研中台综合合并规格 (All-in-One Multi-Asset Synthesis)

**功能编号**：020-all-in-one-multi-asset-synthesis  
**创建日期**：2026-09-30  
**状态**：规划中 (Approved for Planning)  
**优先级**：P0 (跨赛道全域资产综合中台与架构级融合)  

---

## 1. 业务背景与问题定义 (Context & Problem Statement)

当前用户 GitHub 账号（`YuxuanWuCN`）下存在多个高价值但历史割裂的工程分支与仓库资产：
1. **`contest-2026` 分支（大创赛国奖级全景工程）**：面向 2026 中国国际大学生创新大赛（达观数据产业命题）。涵盖 202 只 A 股高景气核心股票池、存储超级周期（Storage Supercycle）、黄金-科技杠铃对冲、CSMAR / TRD_Dalyr 权威行情走步评测（M0-M6）、Fama-MacBeth 滚动截面定价、LLM 情绪三角预测、完整的大创赛产业申报书与 18 页金牌路演 PPT 逐页演讲文稿及专家攻防 QA 手册。
2. **`v3.1` 分支（郑商所商品期现套保衍生版）**：面向郑商所纯碱/玻璃产业链。涵盖 ADR-0001 两层解耦架构（定性事实标签与定量一票否决代码门禁）、ADR-0002 物理因果本体论（天然碱-纯碱-光伏/浮法玻璃-终端组件）、跨资产期望盈余（TES）管道、郑商所官方注册仓单与期现基差跟踪、极星 19.5 原生量化插件（CZCE_19_5_DualProduct_Plugin）及 343 项全绿自动化测试套件。**关键技术事实：`v3.1` 为孤立分支（Orphan Branch），无共同 Git 根节点**。
3. **`main` 分支（开源主干与双核融合前端）**：已融合 Spec 019 适老银发理财门面与硬核学术计量经济学面板，代码干净、开源合规。
4. **`serenity-chokepoint-investing-enhanced` 仓库**：AI 基础设施供应链瓶颈（Chokepoint）定性与定量两阶段研究技能，是 ADR-0001 和两层解耦的理论发源地。
5. **`JC1503-Python-Arsenal` 与 `new-class` 仓库**：个人 Python OOP/课程作业仓，无量化金融逻辑，属正交外围资产。

### 核心决策：禁止暴力 Git Merge，必须实施“架构级多资产中台合成”
若通过原始的 `git merge origin/v3.1 --allow-unrelated-histories` 强行合并，将产生数十个同名目录（`src/`、`tests/`、`docs/`、`data/`、`README.md`）的灾难性代码覆盖，导致 202 只股票池与 12 只商品标的冲突、测试用例击穿、赛事合规性污染。
因此，必须采用**规范驱动的“模块化多资产 Monorepo 中台合成”方案（Rainbow-FinGPT v4.0）**，实现：
- 底层计量与因果推理算法沉淀共享；
- 权益（Equity）、大宗商品（Commodity）、普惠财富（Wealth）三轨独立运行；
- 竞赛申报与路演材料（大创赛 vs 郑商所杯）物理隔离；
- Web 端四合一无缝穿透交互中台。

---

## 2. 用户场景与故事 (User Scenarios & Stories)

### User Story 1 - 跨赛道多维评审与产业申报 (Priority: P0)
作为大创赛（互联网+/中国国际大学生创新大赛）或郑商所杯评审专家，我希望看到一个逻辑自洽、边界清晰的产业答卷：
- 大创赛评委能够查阅 202 只 A 股高景气科技资产池、CSMAR 权威回测以及存储/黄金杠铃组合，不受大宗期货细节的冗余干扰；
- 郑商所杯评委能够查阅纯碱/玻璃产业链时空套保、极星 19.5 交易插件与注册仓单对冲；
- 评委能够清晰看到系统具备全域多资产扩展能力（Multi-Asset Ready），体现出极高的商业与工程上限。

### User Story 2 - 量化研究员与算法工程师 (Priority: P0)
作为量化算法开发者，我希望在统一的代码仓库中：
- 共享一套高精度、经过 Newey-West HAC 校验的 Fama-MacBeth 回归与 Schmidt 正交化数学核心库（`src/core/math/`）；
- 共享一套具备定性事实标签（`[FACT]`）一票否决门禁的因果推理引擎（`src/intelligence/`）；
- 随时通过命令行或参数分别运行 A 股权益回测（`src/assets/equity/`）或大宗商品跨资产期望盈余计算（`src/assets/commodity/`），两套管线互不侵扰、依赖清晰。

### User Story 3 - 终端用户与路演现场交互 (Priority: P1)
作为系统终端使用者或路演现场演示人，我希望打开统一 Web 终端即可自由切换：
- **模式 1**：银发普惠理财门面（温暖易懂、半圆仪表盘、SVG 绝对收益）；
- **模式 2**：A 股学术计量看板（Fama-MacBeth 因子暴露、CSMAR 映射、202 标的打分）；
- **模式 3**：郑商所跨资产双轨套保（纯碱/玻璃时空 NALE、基差与仓单）；
- **模式 4**：产业链因果拓扑图谱（Serenity Chokepoint 瓶颈推演）。

---

## 3. 功能需求与验收标准 (Functional Requirements & AC)

### FR-1: 核心计算与因果算法层统一提取 (Core Algorithms)
- **AC 1.1**：提取通用的 Fama-MacBeth 2-Stage 回归、Newey-West HAC 稳健标准误、Schmidt 正交化、信息比率（IR）计算函数至 `src/core/math/`，供所有资产轨道共享。
- **AC 1.2**：提取 ADR-0001 两层解耦引擎（定性事实标签与代码门禁）及 ADR-0002 产业链物理因果本体层次至 `src/intelligence/`。
- **AC 1.3**：集成 `serenity-chokepoint-investing-enhanced` 的 Chokepoint 评分与拓扑推演逻辑，统一接口标准。

### FR-2: 资产轨道解耦与独立流水线 (Asset Domain Pipelines)
- **AC 2.1**：**权益资产轨道 (`src/assets/equity/`)** 完整接管 `contest-2026` 中的 202 只 A 股标的池、存储超级周期回测、黄金杠铃策略、CSMAR/TRD_Dalyr 走步评测（M0-M6）。
- **AC 2.2**：**商品衍生品轨道 (`src/assets/commodity/`)** 完整吸收 `v3.1` 中的纯碱-玻璃产业链跨资产期望盈余（TES）管道、极星 19.5 插件规范与注册仓单对冲模型。
- **AC 2.3**：**普惠财富轨道 (`src/assets/wealth/`)** 继承 `main` 中的银发安心配置算法。

### FR-3: 赛事申报材料与路演工件物理隔离 (Competition Isolation)
- **AC 3.1**：建立 `competitions/dachuang_2026/` 目录，完整保留并规范大创赛申报书、18 页金牌路演 PPT 逐页讲稿、专家答辩攻防手册、达观数据方案。
- **AC 3.2**：建立 `competitions/czce_futures/` 目录，完整保留郑商所杯纯碱/玻璃研究计划、论文、极星实盘说明与双轨保障包材料。
- **AC 3.3**：各赛道申报文档严格隔离，确保提交任意赛事时导出材料纯净、无赛道串味。

### FR-4: 测试套件分层与回归保障 (Hierarchical Quality Testing)
- **AC 4.1**：重构测试目录为 `tests/core/`、`tests/equity/`、`tests/commodity/`、`tests/integration/`。
- **AC 4.2**：保证 `contest-2026` 既有 92+ 项测试与 `v3.1` 既有 343 项测试在各自测试子集下 100% 通过（Exit Code 0）。
- **AC 4.3**：新增跨资产集成契约测试（`tests/integration/test_multi_asset_synthesis.py`），验证共享内核与解耦边界。

### FR-5: 统一多模式交互终端构建 (Unified Multi-Mode Web Terminal)
- **AC 5.1**：在主看板导航栏提供全局资产轨道切换导航（普惠理财 / A 股量化研报 / 郑商所期现套保 / 产业链因果图谱）。
- **AC 5.2**：保持单文件离线容灾特性（弱网或断网环境自动回退至同构本地快照，零白屏）。

---

## 4. 非功能性需求 (Non-Functional Requirements)

1. **版本与历史可溯性**：采用 Git Worktree / Subtree 或干净的 Cherry-pick 重构提交，禁止直接使用带破坏性的强制覆写。
2. **零根目录污染**：严格遵循用户全局守则，杜绝根目录散落碎片文件，相似资产高内聚归拢。
3. **数据因果性与学术诚信**：所有时序回测严格遵守 rolling 时间窗口，严禁前视偏差，数据来源（CSMAR / CZCE）公开可复核。
