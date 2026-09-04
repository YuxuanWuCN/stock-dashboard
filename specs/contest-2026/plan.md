# 实现计划：Rainbow-FinGPT 核心代码与架构系统级优化

**分支**：`contest-2026` | **日期**：2026-09-04 | **规格**：`specs/contest-2026/spec.md`  
**输入**：来自 `specs/contest-2026/spec.md` 的功能规格与 `specs/contest-2026/gap-analysis.md` 完成度差距分析

---

## 概要

在校赛阶段申报材料顺利提交后，系统全面转向备战省赛与国赛的高标准工程与算法深化。针对系统当前存在的**“单体大文件耦合重、因子正交化模块缺失（立新能源案例收益无法剔除风格暴露）、市场状态机与动态仓位未接入统一 DAG 调度器、批量分析耗时偏长”**等技术债务与规格差距，本计划规划系统级代码重构与性能优化：

1. **核心算法补全**：实现 `src/pricing/factor_orthogonalization.py`（Schmidt 正交化与 PCA 降维），解决特质 Alpha 被 Carhart 四因子风格污染的问题。
2. **架构解耦重构**：拆解 58KB 单体大文件 `src/build_ranking.py` 和 39KB `src/fetch_data.py`，提炼出清晰的 Pipeline 服务层与缓存适配层。
3. **策略增强统一集成**：将 `market_regime_detector.py`（牛/熊/震荡状态机）、`dynamic_position_sizer.py`（动态仓位）、`rolling_direction_calibration.py`（TFAC 时变因子校准）深度集成至 `UnifiedPipelineRunner`。
4. **计算性能与数据管线优化**：通过 NumPy/Pandas 矢量化替代行遍历，优化 156 标的每日打分管道，降低 40% 运行时间与内存开销。
5. **质量保证与全绿门禁**：遵循 `AGENTS.md` 与数学建模规范，补充边界与反事实单元测试，确保现有 92+ 项测试零退化。

---

## 技术背景

**Language/Version**: Python 3.13.14, ES6+ JavaScript  
**Primary Dependencies**: pandas, numpy, scipy, statsmodels, scikit-learn, pytest  
**Storage**: Local JSON (docs/data/paper, docs/data/quantitative), CSV fixtures  
**Testing**: pytest  
**Target Platform**: Windows 11, Linux CI/CD, GitHub Pages  
**Project Type**: Quantitative Engine + Web Dashboard  
**Performance Goals**: 单标的端到端 DAG < 250ms，156 标的批量打分缩短 >= 40%，内存峰值 < 500MB  
**Constraints**: 严格遵守真实口径，禁止伪造收益，严禁时序打乱与未来函数，离线测试可复现  

---

## 宪章检查 (Constitution Checklist)

*关卡：必须在开发前通过，并在设计与测试后重新检查。*

| 宪章原则 | 检查项 | 是否合规 | 落实措施 |
|---------|-------|---------|---------|
| **I. 模块优先与单一职责** | 消除单体神类/大脚本，接口自包含 | ✅ 通过 | 拆分 `build_ranking.py`，提炼独立 Scoring、Formatting 与 Ranking 服务 |
| **II. 测试优先与质量门禁** | 变更前编写测试，覆盖正常/边界/缺失路径 | ✅ 通过 | 为新增因子正交化编写独立测试 `tests/test_factor_orthogonalization.py` |
| **III. 数据与时序因果性** | 不覆盖原始数据，不混淆时间序列 | ✅ 通过 | 使用 rolling 严格避免前视偏差，历史净值保持离线版本化 |
| **IV. Agent 独立复核** | 独立小样本断言核验数学指标 | ✅ 通过 | 为 Schmidt 正交化提供已知解析解的小样本数值对齐核验 |
| **V. 性能与优雅降级** | 本地缓存优先，无网或超时平滑回退 | ✅ 通过 | 统一缓存适配层，支持离线 Mock 快速运行端到端 Pipeline |

---

## 项目结构规划 (Project Layout)

### 1. 规范与文档工件 (此功能)

```text
specs/contest-2026/
├── spec.md                       # 功能规格说明书
├── plan.md                       # 本实现计划文档
├── research.md                   # 阶段 0 技术调研与算法论证
├── data-model.md                 # 阶段 1 数据模型与核心实体
├── quickstart.md                 # 阶段 1 快速上手指南
├── contracts/                    # 阶段 1 API 契约定义
│   ├── factor_orthogonalization.md # 因子正交化契约
│   ├── regime_and_sizing.md        # 状态机与仓位契约
│   └── causal_inference.md         # 学术创新因果推断契约
├── gap-analysis.md               # 比赛要求完成度差距分析
└── tasks.md                      # 阶段 2 详细执行任务清单 (待生成)
```

### 2. 源代码重构后目录结构 (仓库根目录)

```text
src/
├── pricing/                      # 定价与因子计量层
│   ├── fama_macbeth.py           # Fama-MacBeth 两阶段回归引擎 (滚动+动态窗口)
│   ├── factor_orthogonalization.py # [NEW] Schmidt 正交化与 PCA 降维
│   ├── rolling_direction_calibration.py # TFAC 时变因子自适应校准
│   └── calibration_config.py     # 校准参数配置
├── risk/                         # 风控与仓位管理层
│   ├── market_regime_detector.py # 牛/熊/震荡宏观市场状态机
│   ├── dynamic_position_sizer.py # 状态依赖动态仓位缩放
│   └── trend_gate.py             # ZigZag + MACD + 均线硬风控门禁
├── analysis/                     # 分析与打分服务
│   ├── factor_quality.py         # 因子 IC/半衰期与拥挤度监控
│   ├── famamacbethv3.py          # V3 计量引擎适配器
│   └── scoringv3.py              # GFCA 几何打分与 NALE 传导
├── data/                         # 数据适配与离线缓存
│   ├── adapter.py                # 统一多源数据适配器
│   ├── cache_manager.py          # [NEW] 股票行情与研报原子化缓存管理器
│   └── benchmark_builder.py      # [NEW] Carhart 四因子构建与维护器
├── pipeline/                     # 流程编排调度
│   ├── unified_pipeline_runner.py # 端到端 DAG 状态机编排器 (集成状态机与正交化)
│   ├── ranking_builder.py        # [REFACTOR] 纯净排行榜生成引擎 (从 build_ranking 拆分)
│   └── report_generator.py       # [REFACTOR] AI 研报与市场洞察合成服务
└── utils.py                      # 数学、统计与文本通用工具库
```

---

## 实施阶段演进 (Implementation Phases)

### 阶段 0：大纲与算法实证调研 (`research.md`)
- [x] 解决因子正交化算法选择（Gram-Schmidt vs OLS 残差 vs 对称正交化）：确认采用多元 OLS 残差正交法（完全剥离 Carhart 4 因子暴露）结合 PCA。
- [x] 确定市场状态机迟滞机制（Hysteresis），避免在牛熊临界点频繁震荡换仓。
- [x] 确定 TFAC 框架（方向自适应校准）与 Hedge 在线学习理论结合点。

### 阶段 1：设计与契约 (`data-model.md`, `contracts/`, `quickstart.md`)
- [x] 固化 `OrthogonalFactor`、`MarketRegime`、`DynamicPosition` 数据模型。
- [x] 制定 `factor_orthogonalization.py`、`regime_and_sizing.md` API 契约。
- [x] 编写 `quickstart.md` 验证示例与使用指南。

### 阶段 2：核心代码重构与实现 (Implementation Tasks)
- **Task 1: 编写并实现因子正交化模块**
  - 实现 `src/pricing/factor_orthogonalization.py`，包含 `orthogonalize_factor` 与 `pca_factor_reduction`。
  - 编写单元测试 `tests/test_factor_orthogonalization.py`（单因子、多因子、带常数项、数值稳定性与异常输入检测）。
- **Task 2: 将状态机与正交化接入统一 DAG 调度器**
  - 修改 `src/pipeline/unified_pipeline_runner.py`，在 Phase 2 前置执行因子正交化，在 Phase 4 结合 `MarketRegimeDetector` 与 `DynamicPositionSizer` 输出真实动态仓位。
  - 更新 `tests/test_unified_pipeline_runner.py`。
- **Task 3: 重构解耦 `src/build_ranking.py`**
  - 分离数据加载、指标计算、排行榜组装、JSON 输出四个核心步骤。
  - 消除冗余代码与全局状态变量，提供结构化类 `RankingPipeline`。
- **Task 4: 数据缓存与批处理性能优化**
  - 优化行情切片与因子计算中的重复拷贝，使用 NumPy 矩阵加速。
  - 运行基准性能测试，验证批量吞吐量提升。

### 阶段 3：全面验证与质量审查 (Verification & Gate Pass)
- 运行完整测试套件：`python -m pytest`，确保新增测试及原 92+ 项测试全绿。
- 运行实盘回测校验：在存储、黄金、绿电三大实证板块运行回测，验证 Sharpe 比率与最大回撤指标符合预期。
- 更新 `AGENTS.md` 与质量状态记录。

---

## 复杂度跟踪

| 涉及变更 | 复杂度来源 | 为什么需要 | 替代方案及为何不可行 |
|---------|-----------|-----------|--------------------|
| 引入 `factor_orthogonalization.py` | 矩阵投影与残差回归 | 解决立新能源案例“高收益但 Alpha 不显著”的硬缺陷，必须证明超额收益不是风格暴露 | 直接用原始因子打分：无法向评委证明纯特质 Alpha，学术硬伤 |
| 解耦 `build_ranking.py` | 拆分 58KB 巨型脚本 | 脚本包含 1200+ 行混乱业务，修改维护极易引发未定义行为 | 保持现状单体脚本：代码评审和后期扩展风险过高 |
| 统一 DAG 注入动态状态机 | 跨模块状态级联 | 使得模拟盘和回测能自动根据大盘牛熊调整仓位系数 | 硬编码固定 100% 仓位：在熊市震荡期无法有效压制最大回撤 |
