# 技术调研与架构决策：020-all-in-one-multi-asset-synthesis
# 全域多资产因果量化投研中台技术论证 (Multi-Asset Synthesis Research)

**规格**：`specs/020-all-in-one-multi-asset-synthesis/spec.md`  
**日期**：2026-09-30  
**状态**：完成 (Resolved)  

---

## 1. 核心架构决策 (Key Architectural Decisions)

### 决策 1：代码合并策略 —— “架构级中台重构 (Monorepo Synthesis)” 替代 “暴力 Git Merge”
- **决策内容**：
  严禁使用 `git merge origin/v3.1 --allow-unrelated-histories` 强行合并。改用“分层命名空间重构与资产领域解耦（Domain-Driven Monorepo Synthesis）”，在主干建立清晰的 `src/core/`（共享算法底座）、`src/assets/equity/`（A 股权益赛道）、`src/assets/commodity/`（大宗期现赛道）、`src/intelligence/`（因果推理与瓶颈拓扑）四层结构。
- **决策理由**：
  1. **Git 历史脱节**：Git 追溯显示，`v3.1` 分支是一个独立的孤立分支（Orphan Branch，首个提交 `0c90cf11` 无父提交），与 `main` 和 `contest-2026` 没有任何共同祖先。使用原生 `git merge` 会因为同名根目录（`src/`、`docs/`、`tests/`、`data/`、`README.md`）引发数百个全量冲突；
  2. **资产逻辑冲突**：`contest-2026` 是 202 只 A 股高景气科技池，`v3.1` 是 12 只郑商所纯碱/玻璃商品期货及产业链标的，直接扁平合并将污染 `watchlist.csv` 与数据快照；
  3. **测试击穿风险**：`v3.1` 拥有 343 项严谨的商品与极星插件测试，`contest-2026` 拥有 92+ 项 A 股计量回归测试。若无命名空间隔离，模块同名导入将导致 pytest 全线崩溃。
- **考虑的替代方案**：
  - *方案 A（直接 Git Merge）*：已被否决，破坏性极大；
  - *方案 B（Git Submodule 子模块）*：在 Windows 本地协作与赛场离线演示时，子模块极其脆弱，经常因路径或未递归拉取导致缺失；
  - *方案 C（分层 Monorepo 架构，采纳）*：代码与数据均享有统一版本控制，资产轨道清晰隔离，易于维护与演示。

---

### 决策 2：仓库纳管边界 —— 精准纳入金融量化核心，剔除无关课程作业
- **决策内容**：
  - **纳入资产**：
    1. `stock-dashboard` 下的核心分支：`contest-2026`（大创赛全套材料与 A 股量化）、`v3.1`（郑商所期现套保系统与 ADR-0001/0002 因果本体）、`main`（银发适老普惠前端与学术面板）、`week1-pca-nale-integration`（PCA 走步降维算法）；
    2. `serenity-chokepoint-investing-enhanced`：纳入为 `src/intelligence/chokepoint/`，作为供应链卡脖子瓶颈拓扑推演的核心组件。
  - **明确剔除资产**：
    1. `JC1503-Python-Arsenal`（个人 Python OOP 与基础数据结构习题代码）；
    2. `new-class`（空项目/课程临时草稿）。
- **决策理由**：
  严格遵循用户全局守则《零根目录污染》与《高密度空间利用原则》，坚决杜绝无关个人学习代码污染商业级与国奖级金融量化工程。

---

### 决策 3：核心数学与计量层统一抽象 (Math & Econometrics Unification)
- **决策内容**：
  将两端重复实现的经典计量经济学算法收敛至 `src/core/math/`：
  - `fama_macbeth.py`：两阶段横截面回归、Newey-West 自适应 HAC 稳健标准误计算（$q = \max(1, \lfloor 4(T/100)^{2/9} \rfloor)$）；
  - `orthogonalization.py`：Gram-Schmidt 因子正交化与 PCA 降维；
  - `alpha_gate.py`：一票否决代码门禁（$p < 0.05$ 且 $IR \ge 0.30$）；
  - `nowcasting.py`：LLM 情感定性标签与数值信号融合算子。
- **决策理由**：
  统一底层数学标准，消除两套系统中对 Newey-West 带宽选取和 t 统计量计算的细微偏差，保证学术严格性与计算口径一致。

---

### 决策 4：赛事材料与评审合规物理隔离 (Competition Isolation)
- **决策内容**：
  创建顶级目录 `competitions/`，分为两个完全独立的命名空间：
  - `competitions/dachuang_2026/`：存放大创赛申报书、18 页金牌路演 PPT 逐页演讲文稿、专家攻防 QA 靶向演练手册、达观数据方案；
  - `competitions/czce_futures/`：存放郑商所杯纯碱/玻璃研究计划、学术论文、极星 19.5 交易端插件配置与套保说明。
- **决策理由**：
  保证在参与“中国国际大学生创新大赛（大创赛）”答辩时，导出的申报书和演示文稿 100% 聚焦于达观数据产业命题与高景气 A 股，不被大宗期货干扰；而在郑商所杯答辩时，材料纯粹聚焦于大宗期现双轨套保。

---

### 决策 5：全域交互终端统一导航 (Unified Frontend Navigation)
- **决策内容**：
  统一 Web 终端（`docs/index.html` 与 `docs/index_wealth.html`）顶部保留全局场景切换导航栏（Tab Bar）：
  1. **【银发普惠】**：适老化安心理财、半圆多彩温度计、原生 SVG 资产增长曲线；
  2. **【A 股学术量化】**：202 标的打分看板、Fama-MacBeth 因子实证面板、CSMAR 权威映射；
  3. **【郑商所产业链套保】**：纯碱/玻璃跨资产期望盈余 (TES) 交互看板、基差与仓单监控、极星插件状态；
  4. **【因果瓶颈拓扑】**：Serenity 供应链 Chokepoint 动态穿透图谱。
- **决策理由**：
  单入口满足大众长辈、金融计量博导、大宗商品产业专家等多角色一屏穿透演示需求，且全量支持离线单文件运行。
