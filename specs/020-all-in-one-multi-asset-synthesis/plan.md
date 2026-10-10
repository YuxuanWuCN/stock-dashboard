# 实现计划：020-all-in-one-multi-asset-synthesis
# Rainbow-FinGPT v4.0 全域多资产因果量化投研中台综合合并规划 (All-in-One Multi-Asset Synthesis Plan)

**分支**：`020-all-in-one-multi-asset-synthesis` | **日期**：2026-09-30 | **规格**：`specs/020-all-in-one-multi-asset-synthesis/spec.md`  
**输入**：来自 `specs/020-all-in-one-multi-asset-synthesis/spec.md` 的功能规格与多分支/多仓整合需求  

---

## 1. 概要 (Summary)

将用户 GitHub 账号（`YuxuanWuCN`）下割裂的高价值核心资产——特别是 `contest-2026`（大创赛国奖级全景工程、202 只 A 股高景气标的池、CSMAR 行情走步评测、金牌路演文稿）与 `v3.1`（郑商所纯碱/玻璃商品期现双轨套保、ADR-0001 两层解耦、ADR-0002 物理因果本体、极星 19.5 插件、343 项测试），辅以 `serenity-chokepoint-investing-enhanced`（供应链卡脖子瓶颈拓扑推演）与 `main`（银发适老普惠与学术双核前端），进行系统级的“全域多资产因果量化投研中台（Rainbow-FinGPT v4.0）”架构合成。

**实施原则与底线**：
1. **严禁暴力 Git Merge**：针对 `v3.1` 为孤立分支（Orphan Branch，无共同父提交）的技术事实，杜绝使用 `--allow-unrelated-histories` 强行合并导致的文件大面积覆写与测试击穿。
2. **分层多资产 Monorepo 解耦**：通过清晰的命名空间隔离（`src/core/math/`、`src/assets/equity/`、`src/assets/commodity/`、`src/intelligence/`），确保各资产轨道独立可测、依赖单向流动。
3. **赛事申报材料物理隔离**：建立 `competitions/dachuang_2026/` 与 `competitions/czce_futures/`，杜绝赛道材料交叉污染。
4. **统一多模交互终端**：Web 端支持银发普惠、A 股量化、郑商所套保、因果拓扑四维一键穿透，并全面保留单文件离线容灾能力。

---

## 2. 技术背景 (Technical Context)

- **语言与解释器**：Python 3.10+ (适配 3.11 / 3.13), ES6+ JavaScript, TypeScript 5.0+, HTML5/SVG
- **主要依赖项**：
  - 数据科学与计量：`pandas`, `numpy`, `scipy`, `statsmodels`, `scikit-learn`
  - Web 与 API 服务：`Flask`, `flask-cors`
  - 前端工程：`React 18`, `Tailwind CSS 3`, `Lucide Icons`, 纯数学原生矢量 SVG
  - 极星量化交易端：`PolarStar 19.5 (CZCE_19_5_DualProduct_Plugin)`
- **存储与数据契约**：
  - 本地快照（`docs/data/` 约 25MB JSON，支持离线秒开）
  - A 股宇宙（`watchlist.csv` 202 标的 + CSMAR/TRD_Dalyr 真实行情与因子面板）
  - 大宗商品基差与注册仓单历史（CZCE 纯碱/玻璃）
- **测试框架**：`pytest`（覆盖数学内核、A 股权益、大宗商品、跨赛道集成）
- **性能与约束指标**：
  - 单标的端到端因果推断与评分 < 200ms
  - 离线单文件加载时间 < 1.0s，零外部 CDN 阻塞
  - 绝对禁止伪造收益、前视偏差与未来函数

---

## 3. 宪章检查与质量门禁 (Constitution Checklist)

| 宪章原则 | 检查项 | 是否合规 | 落实措施 |
|---------|-------|---------|---------|
| **I. 模块优先与单一职责** | 消除神类，多资产领域严格解耦 | ✅ 通过 | 拆分为 `core/`、`assets/equity/`、`assets/commodity/`，职责自包含 |
| **II. 测试优先与质量门禁** | 变更前编写契约测试，覆盖正常/异常分支 | ✅ 通过 | 建立分层测试集，确保 `contest-2026` 与 `v3.1` 原有数百项测试 100% 绿色 |
| **III. 数据因果性与真实口径** | 不打乱时间序列，不伪造数据，rolling 避免未来函数 | ✅ 通过 | 严格采用 CSMAR 走步评测（M0-M6）与郑商所官方注册仓单数据 |
| **IV. Agent 独立复核** | 独立小样本断言与解析解校验 | ✅ 通过 | Newey-West HAC 异方差稳健 t 值与信息比率提供手算小样本核验基准 |
| **V. 零根目录污染** | 严禁根目录散落临时文件与无关作业 | ✅ 通过 | 精准纳入金融资产，剔除 Python 基础习题库（JC1503），历史由 Git 保证 |

---

## 4. 项目结构与目录映射 (Target Project Architecture)

```text
Rainbow_FinGPTv2/
├── .specify/                         # 规范驱动开发模板与脚本
├── specs/                            # 历代功能规格与实施计划
│   ├── 001 ~ 019                     # 既有规格
│   └── 020-all-in-one-multi-asset-synthesis/
│       ├── spec.md                   # 综合合并功能规格书
│       ├── plan.md                   # 本实施计划
│       ├── research.md               # 阶段 0 技术调研与决策
│       ├── data-model.md             # 阶段 1 数据模型契约
│       ├── quickstart.md             # 阶段 1 快速上手指南
│       └── contracts/                # OpenAPI 契约
├── competitions/                     # 赛事申报与答辩材料隔离区 (全新)
│   ├── dachuang_2026/                # 大创赛 (中国国际大学生创新大赛) 专属
│   │   ├── 申报书与填报版 (md/docx/pdf)
│   │   ├── 18页金牌路演PPT逐页演讲文稿_最终完美版.md
│   │   └── 评委答辩专家攻防QA靶向演练手册.md
│   └── czce_futures/                 # 郑商所杯 (纯碱/玻璃商品衍生品) 专属
│       ├── 01_研究计划与论文/
│       ├── 02_极星量化与实盘/
│       └── 03_算法模型与回测/
├── src/                              # 多资产量化中台源码
│   ├── core/                         # 共享底层内核
│   │   ├── math/                     # Fama-MacBeth, HAC, Schmidt 正交化, IR
│   │   └── data/                     # 统一行情与宏观因子加载器
│   ├── intelligence/                 # 因果推理与产业拓扑
│   │   ├── two_layer_engine.py       # ADR-0001 两层解耦与一票否决代码门禁
│   │   ├── causal_ontology.py        # ADR-0002 产业链物理工艺本体
│   │   ├── chokepoint/               # 来自 serenity-chokepoint 供应链瓶颈推演
│   │   └── nale_graph/               # 时空图卷积与涨停溢出
│   ├── assets/                       # 资产领域流水线 (完全解耦)
│   │   ├── equity/                   # A 股权益赛道 (来自 contest-2026)
│   │   │   ├── storage_runner.py     # 存储芯片超级周期
│   │   │   ├── gold_barbell.py       # 黄金杠铃对冲
│   │   │   └── csmar_pipeline.py     # 202 标的 CSMAR 走步评测
│   │   ├── commodity/                # 大宗商品赛道 (来自 v3.1)
│   │   │   ├── tes_pipeline.py       # 跨资产期望盈余计算
│   │   │   ├── polarstar_plugin/     # 极星 19.5 量化插件
│   │   │   └── warehouse_receipts.py # 仓单与基差跟踪
│   │   └── wealth/                   # 普惠财富赛道 (来自 main)
│   │       └── silver_allocation.py  # 银发安心配置算法
│   └── server.py                     # 多资产统一 API 网关
├── docs/                             # 统一全景交互前端 (支持单文件离线)
│   ├── index_wealth.html             # 银发普惠与学术双核终端 (React 18 + SVG)
│   ├── index.html                    # A 股机构量化看板
│   ├── index_commodity.html          # 郑商所期现套保看板
│   └── data/                         # 离线同构学术快照
└── tests/                            # 分层测试套件
    ├── core/                         # 基础算法与数学单元测试
    ├── equity/                       # A 股回测与策略测试
    ├── commodity/                    # 大宗期货与极星插件测试 (343 项)
    └── integration/                  # 跨赛道集成契约测试
```

---

## 5. 阶段实施计划 (Phased Execution Plan)

### 阶段 0：大纲与调研（已完成 ✅）
- 完成 `research.md`，确立架构级 Monorepo 合成路线，明确拒绝暴力 `git merge`。
- 确认纳入资产列表（`contest-2026`, `v3.1`, `main`, `serenity-chokepoint`）与剔除列表（`JC1503`, `new-class`）。

### 阶段 1：数据模型与契约定义（已完成 ✅）
- 完成 `data-model.md`，确立多资产标的、工艺节点、定性命题、代码门禁及 TES 期望盈余统一实体。
- 编写 `contracts/multi-asset-api.json` 与 `quickstart.md`。

### 阶段 2：资产目录重构与隔离区建立 (Structural Isolation)
1. **建立赛事材料隔离区**：
   - 提取 `origin/contest-2026` 的大赛申报书、18 页金牌 PPT、攻防手册至 `competitions/dachuang_2026/`；
   - 提取 `origin/v3.1` 的研究计划、论文、极星说明至 `competitions/czce_futures/`。
2. **清洗根目录**：
   - 将根目录下散落的旧版 PPT 文本、答卷草稿移动至对应的 `competitions/` 子目录，达成《零根目录污染》。

### 阶段 3：算法与业务代码融合 (Codebase Synthesis)
1. **下沉共享数学内核**：
   - 将 `v3.1` 与 `contest-2026` 中的 Fama-MacBeth 2-Stage、Newey-West HAC、Schmidt 正交化合并至 `src/core/math/`。
2. **集成因果推理与 Chokepoint 技能**：
   - 将 `v3.1` 的 ADR-0001 两层解耦与 ADR-0002 物理工艺本体迁移至 `src/intelligence/`；
   - 将 `serenity-chokepoint-investing-enhanced` 的瓶颈打分与假设检验能力无缝封装至 `src/intelligence/chokepoint/`。
3. **隔离资产业务流水线**：
   - `contest-2026` 的 202 标的打分与回测归拢至 `src/assets/equity/`；
   - `v3.1` 的纯碱玻璃 TES 管道与极星插件归拢至 `src/assets/commodity/`。

### 阶段 4：测试套件验证与门禁运行 (Test Suite Verification)
1. 迁移并重组测试用例，确保 `tests/commodity/` 343 项测试在纯碱/玻璃赛道全绿；
2. 确保 `tests/equity/` 在 202 只 A 股回测下全绿；
3. 新增 `tests/integration/test_multi_asset_synthesis.py`，验证共享内核的数学一致性。

### 阶段 5：统一全景交互终端与文档定稿 (Web Terminal & Handoff)
1. 完善 Web 终端全局导航栏，支持四个专业 Tab 间毫秒级平滑穿透；
2. 重新编译单文件离线容灾产物；
3. 更新主根目录 `README.md`，全面呈现 Rainbow-FinGPT v4.0 全域多资产投研中台全景图。