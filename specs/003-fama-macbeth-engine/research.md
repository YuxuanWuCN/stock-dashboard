# 研究文档: Fama-MacBeth 多因子引擎（Phase 1）

**Feature**: 003-fama-macbeth-engine | **Date**: 2026-08-15 | **来源**: spec.md 技术上下文 + 现状调研

> 格式约定：每项研究问题给出 决策 / 理由 / 考虑过的替代方案。

## R1. 回归统计库选择（依赖决策）

- **决策**：使用 statsmodels（OLS + 稳健标准误）实现阶段一时间序列回归；Fama-MacBeth 横截面聚合与 t 统计量手工实现（numpy）；SQLite 用 Python 标准库 sqlite3。
- **理由**：蓝图明示"Link SQLite database to run time-series statsmodels regressions"；statsmodels 提供异方差自相关稳健标准误（HC1/HAC/Newey-West）与 VIF 共线性诊断，正是 Alpha 显著性推断所需；横截面 FM 聚合只是"每日横截面回归系数的时间序列均值 ± 标准误"，手写更透明可控、便于独立复核。项目现有约束"仅依赖 numpy，无 sklearn"（src/analysis/similarity.py）针对机器学习 KNN，不排斥统计推断库；statsmodels 无 ML 依赖。
- **当前缺口**：venv 实测 statsmodels 与 scipy 均未安装（2026-08-15 实测），需 pip install statsmodels（自动带 scipy/patsy），并同步更新 requirements.txt。
- **替代方案**：① linearmodels（自带 FamaMacBeth 类）——功能富余（面板 IV 等）、依赖更重，与本 feature 仅需 OLS+FM 聚合的需求不匹配，拒绝；② 纯 numpy 手写 OLS——失去稳健标准误与 VIF，统计推断可信度下降，拒绝；③ scikit-learn LinearRegression——无 p 值/HAC/VIF 语义，拒绝。

## R2. 两阶段回归方法论与 Alpha 口径

- **决策**：
  - **阶段一（时间序列，每标的）**：(R_it - rf_t) = alpha_i + beta_i1*MKT_t + beta_i2*SMB_t + beta_i3*HML_t + beta_i4*MOM_t + eps_it，窗口 = 最近 5 年（约 1250 交易日），锚定到最新公共交易日；alpha_i 的 p 值用 HAC（Newey-West, maxlags=5，可配置）标准误计算。
  - **门控口径**：使用阶段一的截距 alpha_i（蓝图公式即如此）：p(alpha_i) < 0.05 且 IR_i = alpha_i / sigma(eps_i) >= 0.3（日频口径，按蓝图原式；不年化，避免口径分歧——记录于假设，Phase 4 校准可再议）。
  - **阶段二（横截面，信息性）**：每日以横截面收益对阶段一 beta 做回归得当日因子溢价 lambda_t，Fama-MacBeth 估计量 = lambda_t 的时间均值，标准误 = std(lambda_t)/sqrt(T)（默认，可选 Newey-West 校正）。阶段二输出进入报告，不参与门控（门控只用阶段一 alpha）。
- **理由**：蓝图硬约束明确指向阶段一截距的 p 值与 alpha/sigma(eps) 的 IR；阶段二按 FM 经典两步法实现，作为风险溢价验证与报告素材，符合"statistically sound pipeline"目标，同时避免把日频横截面噪声引入硬门控。
- **替代方案**：① 门控改用横截面 alpha（FM intercept 均值）——日频横截面截距噪声大、且与蓝图公式不符，拒绝；② 全部年化后再门控——引入年化约定分歧，蓝图原式即日频，拒绝；③ 只用月度数据做 FM——与"5 年日线"蓝图口径不符，样本量骤降，拒绝。

## R3. 因子 CSV 契约（用户手工提供，CSMAR/RESSET 导出）

- **决策**：定义规范化 CSV 契约（见 contracts/factors-csv.md）：UTF-8、首行表头、列序 date,MKT,SMB,HML,MOM[,rf]、date 为 ISO YYYY-MM-DD、数值列允许空值（该行剔除并计入质量报告）、允许额外 source/version 元信息列。加载器对缺失列/重复日期/空值缺口超阈值（默认 5%）执行校验并明确报错（FR-001）。
- **理由**：用户导出格式不可控，契约是唯一可测试的边界；日期主键与 SQLite 入库/对齐逻辑直接对应。
- **替代方案**：① 直接约定 CSMAR 原始格式入库——导出表结构多变（含个股/日期透视），转换逻辑脆弱，拒绝；② 仅支持夹具格式——上线不可用，违背 spec 澄清 Q1，拒绝。

## R4. SQLite 因子库设计

- **决策**：docs/data/factors/factors.db；表 factors(date TEXT PRIMARY KEY, mkt REAL, smb REAL, hml REAL, mom REAL, rf REAL) + 表 source_meta(key TEXT PRIMARY KEY, value TEXT)（记录来源、版本、入库时间）；写入幂等（同日 UPSERT），查询按日期区间。
- **理由**：与项目 docs/data 数据体系一致；单表日期主键满足"无重复日期"FR-002；source_meta 支撑"来源版本标识"可审计要求。
- **替代方案**：① 每因子一表——四表联合查询啰嗦且无收益；② 全内存 DataFrame 不入库——不可审计、无法跨运行复用，拒绝；③ 并入现有 K 线 JSON 体系——因子是全局序列（非按标的），JSON 每标的存储结构不匹配，拒绝。

## R5. 交易日对齐与无前视保证

- **决策**：对齐 = 因子日期 ∩ 标的 K 线日期（交集策略，spec Edge Case 已定）；剔除日记录到数据质量报告；回归窗口右端 = 分析日（最新公共交易日），只用截至该日数据（锚定窗口，非滚动）；泄漏注入测试必须能触发失败（SC-004）。
- **理由**：交集最保守（不伪造因子值）；锚定窗口满足蓝图"5 年窗口"且无前视；与项目 KNN 滚动标准化防前视的既有原则一致（AGENTS.md）。
- **替代方案**：① 并集 + 前向填充因子——填充引入伪造，违背"不伪造数据"原则，拒绝；② 滚动窗口逐日重估——留给 Phase 4 校准，本 feature 锚定即可。

## R6. 无风险利率口径

- **决策**：优先使用 CSV 中的 rf 列（如导出含）；否则用可配置年化固定值（默认 2.5%），按 252 交易日换算为日频（与收益率口径一致）。
- **理由**：A 股无统一日频无风险利率；10Y 国债到期收益率序列可取但用户 CSV 未必含，固定近似 + 可配置是 spec 假设既定默认。
- **替代方案**：强制要求 rf 列——增加用户导出负担；用 1 年期定存利率——与 10Y 差异微小，默认值可配置已覆盖。

## R7. 门控接入点与降级策略

- **决策**：在 src/build_ranking.py 机会分计算之后、激进组合候选构建之前插入 alpha_gate 判定（src/analysis 新增模块）；门控字段写入 ranking.json 与 {code}.json（schema 校验同步扩展）；通过数 < min_size(5) 时按原机会分回退补齐并告警标注（spec 假设既定）。
- **理由**：与蓝图"Integrate Fama-MacBeth 2-stage regression in build_ranking.py / Select assets with statistically significant residual Alpha"一致；降级策略避免空组合（spec 假设已确认）。
- **替代方案**：门控放权重乘数（软门控）——蓝图要求硬门控（downgraded to Watchlist），拒绝；先跑通再接入主流水线（旁路脚本）——违背"接入排行榜"验收场景，拒绝。

## R8. 测试与可复现策略

- **决策**：全部测试离线夹具化——合成因子 CSV（含已知构造的 MKT/SMB/HML/MOM 序列）+ 合成 K 线（注入已知 alpha 与 beta），无外部请求（对齐 FR-010）；测试分层：单元（加载器/校验/回归/门控）、集成（build_ranking mock 流水线）、泄漏注入（未来因子值污染 → 断言触发失败）；独立手算复核 3 只小样本（SC-006）；新测试文件 tests/test_fama_macbeth.py（单元）+ tests/test_fama_macbeth_integration.py（集成），并注册进 small/medium 门禁批次（.quality-gates.json custom_commands 扩展）。
- **理由**：AGENTS.md 要求 mock/离线夹具可复现、边界/缺失/失败路径全覆盖；SC-004 要求 100% 覆盖率。
- **替代方案**：用真实 akshare 行情跑测试——不可复现、慢，拒绝；只测回归不测泄漏——违背 SC-004 与蓝图"zero future data leaks"质量门，拒绝。

## R9. 性能预算

- **决策**：不做并行化。202 只 × 1250 日 × 4 回归元的 OLS（statsmodels 单标的 ~ms 级）+ 约 1250 次横截面回归，总量预计 < 1 分钟，远低于 SC-005 的 15 分钟预算。若实测超预算再考虑向量化横截面。
- **理由**：规模小，简单优先（KISS 精神）；预留配置项即可。

## 未决项

- 无。spec 澄清 Q1（CSV 来源）已解决；statsmodels 缺失已确认并纳入 R1 决策。