# Feature Specification: 师叔 claw-quant 核心融合进 2.0版 判断主流程

**Feature Branch**: `005-claw-quant-fusion`

**Created**: 2026-08-17

**Status**: Draft

**Input**: User description: "直接把师叔的项目综合结合一下"（claw-quant 核心：前沿消息抓取、因子半衰期/拥挤度、信念-执行分离、约束监管）

## 背景 (Background)

**问题描述（诚实基线）**：当前 2.0版 的排名主流程 `compute_composite_score` = 风险分 + 技术分（K线/均线/RSI/MACD/布林）+ 行业分 + 相似度预测分，**全是历史股价的滞后信息**。师叔 claw-quant 的"真谛"是用**前沿消息**（海关出口、现货价格、原厂报价、资本开支指引）打破财报 1~3 个月时滞，并用**因子半衰期/拥挤度**防"因子动物园"、用**信念-执行分离**防止"预测错≠执行错"、用**约束监管**防单一暴露失控。这四点当前均未落地。

**规格写作前的侦察结论（2026-08-17 静态审阅 + 数据抽查）**：

1. **领先指标是空壳**：`src/analysis/leading_indicators.py` 只 import numpy/pandas，唯一产出函数 `generate_synthetic_leading_signal` 生成合成假数据（默认平稳），无任何 akshare/海关/现货 import。真实数据接入率 0%。
2. **领先信号不进评分**：`src/analysis/scoring.py` 的 `compute_composite_score` 签名（risk/technical/industry/similarity + 两个预测列表）完全不含领先指标参数；`compute_technical_score`/`compute_industry_score` 也不读 leading 信号。评分接入率 0%。
3. **已有可复用零件**：`INDUSTRY_LEADING_MAP`（半导体/光通信/新能源/贵金属四类 → 海关/现货/订单流映射）、`calculate_momentum_and_inflection`（动量斜率 + 拐点判定）已存在且设计正确；`leading_indicator_tracker.py`（FACT/OPINION/INFERENCE 三元标注）只进研报文本、不进评分。
4. **因子层现状**：`src/analysis/factor_db.py` 存因子值，但无 IC/半衰期/拥挤度指标；`fama_macbeth.py` 已做四因子回归 + HAC + IR 门控（p<0.05 且 IR≥0.3），可作为半衰期/拥挤度的数据基础。
5. **组合层现状**：`src/strategies/` 有纸面组合（aggressive/defensive/global/tech/bluechip），但无 Damodaran 式约束监管（暴露上限/行业集中/换手等），无 thesis(信念) 与 holdings(执行) 的显式分离。
6. **环境约束**：沙箱无法连通外部数据源（akshare 海关/现货），真实抓取需用户本地电脑运行。因此本 feature 的策略是**代码全量落地 + 离线夹具/模拟测试**，真实数据抓取脚本交付用户本地执行（与项目既有"外部行情请求必须可 mock 复现"约定一致）。

**范围界定**：本 feature 按优先级分五层（对应 claw-quant 的 Fisher→SFM→Graham→Markowitz+Damodaran 架构）：① P1 领先指标接真实数据源；② P1 领先信号进评分；③ P2 因子半衰期/拥挤度（SFM 层）；④ P2 信念-执行分离（Graham 层）；⑤ P3 约束监管（Damodaran 层）。**不做**：不改动技术分/风险分的既有因子权重（只新增领先分量，不推翻现有）、不做实盘交易（仍是研究看板）、不引入外部付费数据源（只用免费 akshare/交易所公开数据）。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 领先指标引擎接真实数据源 (Priority: P1)

项目所有者要让 `LeadingIndicatorEngine` 具备真实数据抓取能力：按 `INDUSTRY_LEADING_MAP` 的分类，从 akshare 免费源抓取海关出口、现货价格、原厂报价等高频领先数据，替代合成假数据；合成数据仅作为离线测试/降级的 fallback。

**Why this priority**: 这是 claw-quant 打破财报时滞的根基。没有真实领先数据，后面"进评分"就是给假数据打分，毫无意义。

**Independent Test**: 用夹具/模拟数据（mock akshare 返回）驱动抓取函数，断言：① 能按 category 解析出正确的数据源与时间序列；② 序列喂入 `calculate_momentum_and_inflection` 得到正确的斜率/拐点；③ 真实源不可用（网络失败）时优雅降级到合成数据并标注 `data_source="synthetic_fallback"`。

**Acceptance Scenarios**:

1. **Given** category="semiconductor" 且 mock akshare 返回存储芯片现货价时间序列，**When** 调用真实抓取，**Then** 输出含 `data_source="akshare"`、`series`（时间序列）、`momentum_metrics`（斜率/拐点）与 `proxy_type`
2. **Given** category 无对应真实源映射（"general"），**When** 抓取，**Then** 输出 `data_source="synthetic_fallback"` + `confidence="low"`，不 crash
3. **Given** akshare 调用抛异常（网络失败/接口变更），**When** 抓取，**Then** 捕获异常 → 降级合成 → `data_source="synthetic_fallback"` + 错误原因记入日志，绝不向上抛
4. **Given** 真实序列含缺失值（海关某月无数据），**When** 计算动量/拐点，**Then** dropna 后仍能计算，样本不足 5 时返回 `confidence="low"` + 平稳默认（与现有实现一致）

---

### User Story 2 - 领先信号进评分 (Priority: P1)

领先指标的拐点/斜率要真正影响综合排名：`compute_composite_score` 新增"领先信号分"组件（正向拐点加分、见顶回落减分、无信号中性），并输出到 reasons/结果字段，让用户在浏览器排行榜和详情页看到排名因前沿信号而变化。

**Why this priority**: 这是"判断标准更新"的直接体现——用户要在浏览器实际看到排名变化，而不是只有一份研报提到领先指标。这是 80% 差距的核心。

**Independent Test**: 构造两只标的：A 有 positive_reversal 领先信号、B 有 negative_reversal，其余技术/行业分相同，断言 A 的 composite 分高于 B；且结果 JSON 含 leading 分量与理由。

**Acceptance Scenarios**:

1. **Given** `compute_composite_score` 传入领先信号结果（positive_reversal），**When** 计算，**Then** opportunity 增加领先分量（正贡献），结果含 `leading_score` 与理由文本
2. **Given** negative_reversal 领先信号，**When** 计算，**Then** 领先分量为负贡献，排名相应下调
3. **Given** 无领先信号（none/flat 或降级合成），**When** 计算，**Then** 领先分量为中性（不增不减），不因缺失而报错（向后兼容）
4. **Given** 前端读取 ranking.json，**When** 渲染排行榜，**Then** 领先信号字段存在，排名与"仅技术+行业"基线相比确有标的因领先信号换位（可观测差异）

---

### User Story 3 - 因子半衰期与拥挤度（SFM 层） (Priority: P2)

因子库要新增两个质量指标：**半衰期**（因子预测力衰减到一半所需天数，防"过时因子"）与**拥挤度**（该因子被市场参与者过度使用的程度，防"因子拥挤踩踏"），并把结论写入因子质量报告供下游参考。

**Why this priority**: 老师信里明确"因子只测暴露不解释价格，关注拥挤度和半衰期"。这是从"堆因子"到"评因子质量"的跃迁，但依赖已有因子回归数据，故 P2。

**Independent Test**: 用合成因子收益序列（已知 IC 衰减规律）喂入，断言半衰期计算接近理论值；构造"人人都在用"的高相关因子组合，断言拥挤度显著高于低相关组合。

**Acceptance Scenarios**:

1. **Given** 一个因子的 IC 时间序列（逐期衰减），**When** 计算半衰期，**Then** 输出半衰期天数（IC 衰减到峰值一半的天数），序列过短时返回 None 并标注
2. **Given** 多个因子的收益序列相关性高（>0.8），**When** 计算拥挤度，**Then** 拥挤度判定为"crowded"；相关性低则"uncrowded"
3. **Given** 半衰期/拥挤度计算完成，**When** 写入因子质量报告，**Then** docs/data/factors/quality_report.json 新增 half_life_days 与 crowding 字段，旧字段保留

---

### User Story 4 - 信念-执行分离（Graham 层） (Priority: P2)

系统要显式区分**信念（thesis，为什么看好/看空及其预期差）**与**执行（holdings，实际仓位）**：价格变动不直接触发买卖，而是触发"信念再验证"；信念未变时执行不因短期波动而漂移。

**Why this priority**: claw-quant 的 Graham 层核心——"预测错≠执行错"。这是从"看价格动就动"到"看信念变不变"的纪律转变，但它是组合/报告层的增强，故 P2。

**Independent Test**: 构造 thesis + holdings 两个独立结构，断言价格波动只更新 holdings 的盯市价值而不改写 thesis；thesis 的"预期差"字段独立于持仓盈亏。

**Acceptance Scenarios**:

1. **Given** 一条 thesis（含核心逻辑 + 预期差 + 失效条件）与对应 holdings，**When** 价格下跌触发再验证，**Then** holdings 盯市更新但 thesis 内容不变，除非失效条件被触发
2. **Given** thesis 的失效条件被触发（如基本面证伪），**When** 再验证，**Then** thesis 状态转为 invalid，并给出重新评估提示
3. **Given** 报告生成，**When** 输出，**Then** 信念与执行分栏呈现（thesis 摘要 / holdings 现状），不混为一谈

---

### User Story 5 - 约束监管（Damodaran 层） (Priority: P3)

组合构建时施加横切约束（单一标的暴露上限、行业集中上限、换手率上限、流动性下限等，共 7 类），超限的候选标的被标记/降权，防止单一暴露失控。

**Why this priority**: 风险纪律的落地，是 claw-quant 的 Damodaran 横切监管。它是锦上添花的稳健性约束，在核心评分链路跑通后再加，故 P3。

**Independent Test**: 构造一个组合候选集，其中一只标的权重远超上限，断言约束引擎将其标记/截断到上限内。

**Acceptance Scenarios**:

1. **Given** 组合候选权重（一只占 60%），**When** 应用约束，**Then** 该标的权重被截断到上限（如 20%），超出部分记录为"约束截断"理由
2. **Given** 行业集中度超限，**When** 应用约束，**Then** 该行业超额标的被标记/降权，输出约束报告
3. **Given** 全部约束通过，**When** 应用，**Then** 组合不变并输出"约束通过"摘要（无副作用）

---

### Edge Cases

- **真实数据源全部不可用**（离线/断网）→ 领先信号降级合成，`data_source="synthetic_fallback"`，评分中性，绝不因网络失败 crash 或给假数据打高分
- **领先信号与行业分类不匹配**（category="general"）→ 合成 fallback，confidence=low
- **因子半衰期序列过短**（<2 期 IC）→ 半衰期 None + 标注，不除零
- **拥挤度无足够因子**（<2 个）→ None + 标注
- **thesis 无 holdings**（新建标的）→ thesis 独立存在，holdings 为空，不报错
- **约束上限配置缺失** → 用默认上限（见假设），并记录"使用默认约束"
- **领先信号与既有技术分冲突**（技术看多但领先见顶回落）→ 两者独立计分，由机会分权重自然平衡，不强制一致（信息单向流动，下游不改上游）

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `LeadingIndicatorEngine` MUST 新增真实数据抓取方法（按 category → 数据源映射调用 akshare 免费接口），输出含 `data_source`（"akshare"/"synthetic_fallback"）、`series`、`momentum_metrics`、`proxy_type`
- **FR-002**: 真实抓取 MUST 异常隔离：akshare 调用失败（网络/接口变更）时降级合成并记录原因，绝不向上抛异常或 crash
- **FR-003**: 合成降级 MUST 保留为离线测试 fallback（`generate_synthetic_leading_signal` 语义不变，仅明确标注数据来源）
- **FR-004**: `compute_composite_score` MUST 新增领先信号分量：positive_reversal 正贡献、negative_reversal 负贡献、none/flat 中性；结果 MUST 含 `leading_score` 与理由
- **FR-005**: 领先信号缺省（无输入或降级合成）时 MUST 保持中性，向后兼容既有调用方（不破坏现有测试）
- **FR-006**: 因子库 MUST 新增半衰期（IC 衰减到峰值一半的天数）与拥挤度（因子收益相关性/使用集中度）计算，写入 `docs/data/factors/quality_report.json`
- **FR-007**: 系统 MUST 建立 thesis（信念：逻辑/预期差/失效条件）与 holdings（执行：仓位/盯市）的分离结构；价格波动不改写 thesis，失效条件触发才转 invalid
- **FR-008**: 组合约束引擎 MUST 施加 7 类横切约束（单标的暴露、行业集中、换手、流动性、市值、估值、现金仓位），超限候选被截断/标记并记录理由
- **FR-009**: 全部新增/修改 MUST 有 pytest 覆盖（正常/边界/缺失/失败路径）；外部数据抓取用 mock/夹具复现，不依赖真实网络
- **FR-010**: 真实数据抓取脚本 MUST 交付为可在用户本地运行的独立入口（如 tools/fetch_leading_data.py），沙箱内不要求真实联网

### Key Entities

- **LeadingSignal（新增）**: 领先指标快照；属性：category、data_source、proxy_type、series、momentum_metrics（slope_pct/momentum/inflection_flag）、confidence
- **LeadingScore（新增）**: 领先信号分值；属性：score（对 opportunity 的贡献）、reason、inflection_flag
- **FactorQuality（新增）**: 因子质量指标；属性：half_life_days、crowding、ic_series
- **Thesis（新增）**: 信念；属性：core_logic、expectation_gap、invalidation_condition、status（valid/invalid）
- **Holdings（新增）**: 执行；属性：weight、mark_to_market、last_rebalance
- **PortfolioConstraints（新增）**: 7 类约束配置 + 违规记录

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `leading_indicators.py` 真实抓取代码落地且通过 mock 测试；`data_source` 能区分 "akshare" 与 "synthetic_fallback"
- **SC-002**: `compute_composite_score` 新增领先分量后，构造的 positive vs negative 领先信号标的综合分有可观测差异（positive > negative），且结果含 `leading_score`
- **SC-003**: 用户浏览器中，ranking.json 新增领先信号字段；至少一只标的的排名因领先信号相对"纯技术+行业"基线发生换位（可观测）
- **SC-004**: 因子质量报告新增 half_life_days 与 crowding，且合成因子测试断言半衰期/拥挤度方向正确
- **SC-005**: thesis 与 holdings 分离结构落地；价格波动不触发 thesis 改写，失效条件触发才转 invalid（测试断言）
- **SC-006**: 组合约束引擎对超限权重/行业集中的截断行为有测试覆盖
- **SC-007**: 新增代码行覆盖 100%，质量门禁 small → medium → heavy 全绿，且不新增历史遗留失败
- **SC-008**: tools/fetch_leading_data.py 交付，用户本地可运行（文档写明数据源与前置依赖），沙箱内不要求真实联网

## Assumptions

- **真实数据源选择**：优先 akshare 免费接口（海关出口月度数据、商品现货价、行业高频指数）；原厂报价函/华强北盘口等无稳定免费接口，用"行业关键词新闻 + 现货价"作为可行代理（老师信中的"领先数据"精神落地为可复现的免费源）
- **领先信号分值权重**：新增领先分量权重小步引入（约 10%~15% 的机会分），避免一次推翻既有技术/行业逻辑；权重可在 config 中调
- **半衰期口径**：IC 时间序列衰减到峰值一半所需的天数；拥挤度用因子收益两两相关的平均绝对值 + 使用集中度（HHI）度量
- **信念-执行分离落点**：先落地在报告/纸面组合层（thesis 结构 + holdings 结构），不引入实盘交易引擎（本系统是研究看板）
- **约束默认上限**：单标的 20%、单一行业 40%、换手率 30%/月、流动性（日成交额下限）、现金仓位 5%~95% 等 7 类，可配置
- **沙箱网络限制**：真实抓取不在沙箱执行；以 mock/夹具验证代码正确性，真实数据由用户本地 `tools/fetch_leading_data.py` 拉取
- **信息单向流动**：下游（执行/评分）不改上游（领先数据/因子）的原始值，只做消费与标注（对应 claw-quant ADR 的信息单向原则）
