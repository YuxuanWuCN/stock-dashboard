# StockDashboard v3.0 蓝图差距分析

> 分析对象：《本人研究成果/stock-dashboard-v3-plan.pdf》（StockDashboard V3.0 Blueprint，2026-08-14，吴宇轩）
> 对照基线：当前代码库 v2.6.0（测试记录/版本/v2.6.0.md；蓝图书写时基线为 v2.5.2，本项目已超前一个小版本）
> 分析日期：2026-08-15
> 分析方式：静态代码审阅（src/、tools/、config/、specs/、reports/prediction_accuracy/README.md），未运行代码、未修改源码

---

## 1. 执行摘要

1. **最大缺口在 Engine 2（Fama-MacBeth 因子回归）**：整个代码库不存在任何因子回归、Alpha、p 值、信息比率相关实现（grep 全库零命中）。这是 v3.0 蓝图中"风险调整后 Alpha 验证"的唯一全新大模块，也是 6 项短板中第 1 项的硬缺口。
2. **Engine 1 缺 FOI 与门控**：RAG 基础设施（新闻抓取、分块、向量库、引用、Monster Reviewer）已相当完整，但情感分析停留在 FinGPT V1 式单一标签（positive/negative/neutral），无 FACT/OPINION/INFERENCE 三角验证，无 Chokepoint Score（0–20）硬门控，定性结果与排行榜完全解耦。
3. **Engine 3 是"工具已备、未接流水线"**：tools/wave_analysis.py 已实现 ZigZag 分段、0.500/0.618 斐波那契度量、MACD/量能背离、报告生成，但在 src/ 中零引用，仅作为单标的 CLI 案例工具使用（立新能源、山东黄金复盘）。
4. **校准闭环比蓝图预期更成熟**：周日校准（calibration.py + apply_calibration.py --auto + weekly_calibration.ps1）、冠军策略衍生 A/B（weekly_champion_analysis.py）、离线预测准确率 harness（prediction_accuracy_harness.py）都已存在。差距在于：指标是 alignment_rate 而非 Brier/cross-entropy，调参是建议式而非贝叶斯自动优化。
5. **重要前置风险**：reports/prediction_accuracy/README.md 的诚实基线显示——纯技术信号方向准确率约等于 50%（噪声水平），LLM 情绪 alignment_rate 约 34.7%（低于抛硬币，疑似系统性反转）。**Phase 2（FOI 管线）应建立在修复情绪信号反转之后**，否则"坏信号 + 好标签"只会放大错误。

---

## 2. 现状基线速览（v2.6.0）

| 层 | 已有模块 | 说明 |
|---|---|---|
| 主流水线 | src/build_ranking.py | 排行榜：KNN 5 日概率 + 20 日动量 + 风险/机会加权（无 Alpha 验证） |
| 排序逻辑 | src/analysis/scoring.py、config.py | 机会分 = forecast_percentile 35% + up_probability 25% + 技术分 20% + 行业分 20%；风险惩罚系数 0.5 |
| KNN | src/analysis/similarity.py | 11 个特征全部技术性（收益/MA 偏离/RSI/MACD/ATR/波动率/量比/行业相对强度），滚动标准化防未来函数 |
| 基本面 | src/analysis/fundamental.py | 源自《会计学大作业2》研究成果的框架（资产占用—融资—周期反转） |
| 策略层 | src/strategies/ | 注册表模式 + 多金叉/涨停回马枪/启明星；已移植 KHunter 市场温度（4 维）与狩猎场（4 种支撑位算法） |
| LLM 层 | src/llm/ | FinGPT DeepSeek 适配器、RAG（news_fetcher/chunker/embeddings/vector_store/citation）、情感分析（FinGPT V1 式）、报告生成、Monster Reviewer |
| 波浪 | tools/wave_analysis.py | ZigZag 分段 + Fib 度量 + 背离检测 + 图文报告（独立 CLI，未接入流水线） |
| 校准 | tools/calibration.py、apply_calibration.py、verify_calibration.py、weekly_calibration.ps1、weekly_champion_analysis.py | 周日 20:00/21:00 定时（Windows 计划任务）；alignment_rate + 调参建议 + --auto 应用 |
| 评估 | tools/prediction_accuracy_harness.py | 离线可复现方向准确率/选择性预测/横截面命中率基线；含随机对照（random_control.py） |
| 质量 | tools/run_quality.ps1、quality_gate.py、mut_runner.py | small → medium → heavy 三级质量门禁 |

---

## 3. 六项短板逐项对照

### 短板 1：无风险调整 Alpha 验证 —— **完全缺失（最大缺口）**

- **蓝图要求**：Fama-MacBeth 两阶段回归（Carhart 4 因子 MKT/SMB/HML/MOM），Alpha p<0.05 且 IR>=0.3 硬门控，再进入组合构建。
- **现状**：机会分 = 预测百分位 + 上涨概率 + 技术分 + 行业分（src/analysis/config.py OPPORTUNITY_WEIGHTS），无任何因子暴露调整。grep "fama/macbeth/statsmodels/carhart" 全库零命中（仅 EMA 平滑参数 alpha 与 matplotlib 透明度）。
- **差距清单**：
  1. 因子数据层：A 股 MKT/SMB/HML/MOM 因子序列（蓝图书写为"从 SQLite 拉 5 年日线"——本项目 K 线在 docs/data/kline/*.json（akshare 缓存），**无 SQLite 因子库**，需新建数据源与加载层）。
  2. 回归模块：时间序列阶段（个股超额收益 ~ 4 因子，得 beta）+ 横截面阶段（收益 ~ beta，得风险溢价）；statsmodels 依赖需加入 venv。
  3. 门控接入 build_ranking.py：Alpha 显著（p<0.05）且 IR>=0.3 才进候选，否则降级 watchlist。
- **优先级**：**Phase 1（第 1–3 周）**。独立性最强、不依赖 LLM，且是 6 项中唯一"完全从零"的模块。

### 短板 2：定性定量割裂 —— **现状确认，架构性差距**

- **蓝图要求**：定性信号（Chokepoint Score 0–20）硬门控 CS>=12，直接影响排行/回测。
- **现状**：src/llm/generate_reports.py 文件头明确声明"附加非阻塞：报告生成失败不影响已有排行数据""独立运行"——定性结果只写 markdown 报告，与排行榜完全解耦（与蓝图短板 2 描述一字不差）。
- **差距清单**：① CS 打分器（工艺节点定位 → 0–20 分）；② CS>=12 硬门控接入 build_ranking；③ 定性到定量的反馈回路。
- **依赖**：CS 打分依赖工艺节点本体（见短板 5）与 FOI 管线（短板 3）。
- **优先级**：Phase 2（第 4–6 周）。

### 短板 3：无 Fact-Opinion-Inference 三角验证 —— **完全缺失**

- **蓝图要求**：句子级 [FACT:source]/[OPINION:holder]/[INFERENCE:chain] 分类 + 跨源交叉验证规则（如供应商订单激增 → 下游应收款交叉核验）。
- **现状**：src/llm/llm_sentiment.py 为 FinGPT V1 式单一情感标签（positive/negative/neutral + score，规则词典降级）；grep "chokepoint/FOI/fact-opinion/三角" 全库零命中。
- **⚠ 关键发现**：reports/prediction_accuracy/README.md 记录 LLM 情绪 alignment_rate 约 34.7%（<50%，低于抛硬币），疑似系统性反转（新闻日期错位或多空映射反了）。**Phase 2 开工前必须先用离线 harness 重算 sentiment_score 到实际方向对齐率并定位反转点**，否则 FOI 建立在已损坏的情绪信号上。
- **优先级**：Phase 2（第 4–6 周），但前置修复情绪信号。

### 短板 4：波浪分析未自动化 —— **工具已备、未接流水线**

- **蓝图要求**：ZigZag 分段算法泛化进 run_strategies.py，扫描全部自选股（蓝图称 202 只），0.500/0.618 猎杀区扫描。
- **现状**：tools/wave_analysis.py（45KB）已实现：ZigZag 极值分割、Fib 回撤/扩展度量、动量与量能背离检测、波动阶段分类、图表与 MD/Docx 报告。src/ 中 0 引用；仅作单标的 CLI 案例（立新能源 001258、山东黄金 600547 复盘报告 2026-08-14 已产出）。
- **差距清单**：① 将 ZigZag 分段/猎杀区判断从 tools 下沉为 src/ 模块；② 接入 run_strategies.py 全池扫描；③ 与狩猎场联动——当前 hunting_ground.py 支撑位是 MA20/关键收盘/关键开盘（KHunter 移植），**非 Fib 波段支撑**，需新增"Wave 4 回调 + 0.500/0.618 支撑带"买点类型；④ 防未来函数测试（ZigZag 峰值位移会引入前视偏差，质量门禁需专项覆盖）。
- **优先级**：Phase 3（第 7–9 周）。移植/复用工具代码，工作量中等。

### 短板 5：KNN 技术空间限制 —— **确认，需数据本体支撑**

- **蓝图要求**：分类距离修正——历史匹配限制在同一 SCNU-SC 工艺节点内（供应链本体）。
- **现状**：src/analysis/config.py FEATURE_NAMES 共 11 个特征，全部为数值技术特征（5/20 日收益、MA 偏离、RSI、MACD、ATR、波动率、量比、行业 20 日相对强度）。无分类特征、无工艺节点本体（grep "process_node/工艺节点/供应链" 零命中）。
- **差距清单**：① 工艺节点本体（Substrate/Epitaxy/Device/Module/Integration 五级，蓝图 Engine 1 定义）；② KNN 分类距离修正（同节点加权/异节点惩罚或样本过滤）；③ 本体数据维护方式（人工/LLM 辅助）。
- **依赖**：本体同时服务 CS 打分（短板 2），建议统一建设。
- **优先级**：Phase 2（本体）+ Phase 3（KNN 修正），横切任务。

### 短板 6：开环校准 —— **现状最接近闭环，差距最小**

- **蓝图要求**：自动周度贝叶斯优化，基于 realized cross-entropy 调 KNN 权重与提示词；Brier score 30 日下降 >=25%。
- **现状**：
  - 已有：calibration.py（alignment_rate、分行业/分市场校准、调参建议：概率阈值/评分权重/提示词/组合策略）、apply_calibration.py（--auto 自动应用）、verify_calibration.py、weekly_calibration.ps1（周日 20:00 计划任务）、weekly_champion_analysis.py（冠军策略 + LLM 衍生 3 变体 A/B）、prediction_accuracy_harness.py（离线方向准确率基线）。
  - 差距：① 无贝叶斯优化器（grep "bayes/optuna/grid_search/scipy.optimize" 零命中）——现为建议式 + --auto 批量应用；② 指标是 alignment_rate 而非蓝图要求的 Brier/cross-entropy；③ 组合权重调整需人工确认（--auto 需显式传入）。
- **优先级**：Phase 4（第 10–12 周）。在现有闭环骨架上替换指标 + 加优化器即可，工作量最小。

---

## 4. 三引擎覆盖矩阵

| 引擎 | 蓝图要求 | 现状覆盖 | 缺口 |
|---|---|---|---|
| Engine 1 定性过滤（FinGPT 式 SCNU-RAG） | FOI 三角验证 + 多源交叉核验 + CS(0–20) 门控 | 60%：RAG 管线（抓取/分块/向量/引用）、Monster Reviewer 审核、DeepSeek V4 Flash 适配 | FOI 句子级分类、跨源交叉验证规则、CS 打分器与硬门控 |
| Engine 2 资产定价（Serenity Layer 2） | Fama-MacBeth 两阶段回归 + Alpha p<0.05 + IR>=0.3 | 0%：完全缺失 | 因子数据层、回归模块、门控接入 |
| Engine 3 战术执行（KHunter） | ZigZag 猎杀区（Wave 4 回调 + 0.500/0.618）+ 量价收缩/MACD 底背离 + 仓位 = Base × 温度% | 70%：wave_analysis 工具、market_temperature（4 维温度到仓位系数）、hunting_ground（4 种支撑位） | ZigZag 接入策略流水线、Fib 猎杀带买点、温度到仓位联动打通 |

---

## 5. 落地顺序建议（对照 12 周路线图修正）

> 蓝图 4 阶段顺序保留，但基于现状做两处修正：增加 Phase 0（情绪信号修复前置），并将数据层建设（因子库/本体）列为横切任务。

| 阶段 | 内容 | 现状基础 | 核心工作项 | 工作量估计 |
|---|---|---|---|---|
| **Phase 0（新增，1 周）** | 修复 LLM 情绪信号反转 | prediction_accuracy_harness 已可离线复算 | 重算 sentiment_score 到方向对齐率，定位反转点（新闻日期错位/多空映射），翻转或重标后验证 >50% | 小 |
| **Phase 1（1–3 周）** | Fama-MacBeth 多因子引擎 | 无 | ①因子数据源选型与加载（A 股 4 因子：CSMAR/RESSET 付费或开源替代）②SQLite/因子库建立 ③两阶段回归模块 ④Alpha p<0.05 + IR>=0.3 门控接入 build_ranking ⑤测试全覆盖 + 独立复核 | 大（唯一全新模块） |
| **Phase 2（4–6 周）** | SCNU-RAG FOI 管线 | RAG 基础完整，情绪信号待修 | ①FOI 句子分类与多源交叉验证 ②工艺节点本体（兼服务 CS 与 KNN）③CS 打分器 ④CS>=12 门控 ⑤200 篇标注集精度 >=90% 验证 | 大 |
| **Phase 3（7–9 周）** | 战术波浪执行器 | wave_analysis.py 工具已备 | ①ZigZag 下沉为 src 模块 ②接入 run_strategies 全池扫描 ③Fib 猎杀带买点（狩猎场新增类型）④防未来函数专项测试 | 中 |
| **Phase 4（10–12 周）** | 贝叶斯校准闭环 | 周日校准闭环已存在 | ①指标切换为 Brier/cross-entropy ②贝叶斯优化器（KNN 权重 + 提示词）③30 日 Brier 下降 >=25% 验证 | 小-中 |

**横切任务**：因子数据源（Phase 1 前置）、工艺节点本体（Phase 2）、质量门禁用例（每阶段随附）、文档与口径收敛（prediction_accuracy README 已提出"80% 口径"定义，建议先行定稿）。

---

## 6. 风险与注意事项

1. **因子数据可得性**：A 股 Fama-French 因子数据主流来源（CSMAR/RESSET）付费；免费替代（开源复算/公开因子库）需验证质量与更新频率。这决定 Phase 1 是否按时启动。
2. **80% 胜率承诺需数据验证**：现有诚实基线（4 万+样本）显示技术信号约 50% 噪声水平。蓝图的"三层过滤乘法效应"是待验证假设而非已证结论——Phase 1 完成后应立即用 harness 口径（方向准确率/横截面命中率）评估，避免过度承诺。
3. **LLM 情绪信号已损坏**：alignment_rate 34.7% 低于抛硬币，Phase 2 前必须修复（Phase 0），否则在坏信号上叠加 FOI 会放大错误。
4. **防未来函数**：ZigZag 峰值位移、KNN 滚动标准化（已有）与因子回归的 beta 估计窗口都必须做无前视泄漏测试（AGENTS.md：时间序列不得随机打乱、外部数据可 mock 复现）。
5. **质量工作流**：任何源码改动遵循 AGENTS.md——先 tools/run_quality.ps1 begin-unit，阅读 bug合集 写明验收标准，按 small → medium → heavy 顺序测试；质量状态与 Bug 历史仅由门禁 CLI 维护。
6. **独立复核**：因子回归的统计显著性、评分边界、KNN 分类修正等关键结论须用独立断言/可手算小样本/独立基准复核并记录局限性（AGENTS.md 第 3 条）。

---

## 7. 局限说明

- 本分析为静态审阅：未运行构建、未执行测试、未抓取行情；文件级结论基于 grep 与抽样阅读，个别模块（如 monster_reviewer、backtest_engine、paper_portfolio 细节）未逐行核对。
- 蓝图 PDF 中若干中文片段提取为占位符，未影响结论。
- 工作量估计为相对量级（小/中/大），供排期参考，非承诺工期。
