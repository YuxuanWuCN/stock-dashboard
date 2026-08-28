# 规范 015: NALE 网络增强型板块图谱与涨停龙头溢出共振引擎 (NALE Sector Graph & Limit-Up Leader Spillover)

## 1. 概述与背景 (Overview)
在 A 股实战交易中，板块主线效应与领头羊身位至关重要。当板块内核心标的（如德明利 001309）冲击涨停封死涨停板时，巨大的封单与情绪动能会向同板块（如存储超级周期/半导体模组）内的滞涨中军与关联标的（如兆易创新、佰维存储、江波龙、太极实业）迅速扩散。

传统单股模型将各股票视为孤岛样本，无法捕捉跨个股的协同共振。本规范（Spec 015）引入 **NALE (Network-Augmented LLM Embeddings，网络增强型大模型嵌入)** 架构，结合金融拓扑图网络，建立板块协同广度与**涨停龙头溢出传导机制**。

---

## 2. 需求规范 (Requirements)

### 2.1 拓扑图网络构建 (`src/graph/sector_graph_engine.py`)
- **REQ-015-01**: **拓扑边双重约束（Dual-Constraint Edges）**：
  - 节点集合 $\mathcal{V}$ 为当前 `watchlist.csv` 中的所有有效标的；
  - 连边条件：两只股票同属于同一题材分类（`category`），**且**近 60 个交易日日收益率的皮尔逊相关系数 $\rho_{ij} > 0.40$。
- **REQ-015-02**: **板块协同广度计算（Sector Breadth）**：
  - 计算板块内同向波动比例：$\text{Breadth} = N_{\text{up}} / N_{\text{total}}$；
  - 记录板块内最新平均涨跌幅与放量乘数。
- **REQ-015-03**: **涨停龙头身位识别（Limit-Up Leader Detection）**：
  - 判定板块内是否存在涨停板（主板涨幅 $\ge 9.8\%$，创业板/科创板涨幅 $\ge 19.8\%$，或当日触及涨停且维持最高位）；
  - 将涨停标的标记为 `Leader (身位龙头)`。

### 2.2 NALE 消息传递与涨停龙头溢出算子
- **REQ-015-04**: **涨停触发扩散（Limit-Up Spillover Activation）**：
  - **触发条件**：仅当板块内检测到至少一只涨停龙头（如德明利封板）时，触发强力溢出扩散机制；
  - **溢出加成**：向同板块内尚未涨停的滞涨中军及补涨标的，按拓扑相关度 $\rho_{ij}$ 注入溢出预期收益：
    $$\Delta R_{5d} = \text{clamp}\left( \text{LeaderRet} \times \rho_{ij} \times 0.25, \; +0.5\%, \; +3.0\% \right)$$
  - **胜率加成**：5 日看涨置信胜率提升 $+5.0\% \sim +12.0\%$。
- **REQ-015-05**: **板块梯队角色划分（Tier Classification）**：
  - 每只股票在板块图谱中被明确打标为以下四种角色之一：
    - `leader`（身位龙头 / 涨停先锋）
    - `core_mid`（中军主力 / 蓄势放量）
    - `follower_catchup`（滞涨补涨 / 溢出受益）
    - `divergent`（离散掉队 / 走势钝化）

### 2.3 数据持久化与评分融合 (`src/build_ranking.py`)
- **REQ-015-06**: 在 `docs/data/analysis/{code}.json` 中注入 `nale_network` 节点属性。
- **REQ-015-07**: 在 `docs/data/analysis/ranking_v3.json` 中，若标的获得龙头涨停溢出加成，将其在排行榜中高亮展示并体现于主要依据。

### 2.4 前端呈现与交互升级 (`docs/index.html` & `docs/assets/app.js`)
- **REQ-015-08**: **详情页卡片**：在单股研究页新增 **“🌐 NALE 板块协同与涨停龙头图谱”** 卡片。
- **REQ-015-09**: **排行榜标签**：在排行榜“主要依据”中展示 `存储·涨停龙头共振` 或 `半导体·龙头溢出` 徽章。

---

## 3. 验收标准 (Acceptance Criteria)
1. 单元测试 `tests/test_sector_graph_engine.py` 覆盖率为 100%。
2. 存储板块在德明利涨停场景下，同板块中军（兆易创新/佰维存储）可成功计算并注入龙头溢出增量。
3. 前端大屏在详情页渲染精美的 NALE 板块协同卡片。
4. 双轴代码审查（Standards Reviewer & Spec Reviewer）100% 通过。
