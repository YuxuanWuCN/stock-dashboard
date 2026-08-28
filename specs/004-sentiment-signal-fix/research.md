# 研究文档: LLM 情绪信号度量与数据口径修复（Phase 0）

**Feature**: 004-sentiment-signal-fix | **Date**: 2026-08-15 | **来源**: spec.md 侦察结论 + 现状调研

> 格式：每项研究问题给出 决策 / 理由 / 考虑过的替代方案。

## R1. 真实收益函数放置位置

- **决策**：在 src/market_feedback.py 新增纯函数 realized_return(close_series, t_index, horizon)（event_date 之后 N 个交易日口径），record_event 调用方（generate_reports.py）改为从 K 线计算真实收益后传入；诊断与回填工具放 tools/（diagnose_sentiment_alignment.py、backfill_market_feedback.py）。
- **理由**：market_feedback.py 已是反馈样本的领域模块，record_event 的契约修正（ret 只收真实收益）在源头执行；tools/ 放一次性/审计类脚本符合项目惯例（wave_analysis、prediction_accuracy_harness 均如此）。
- **替代方案**：① 放 src/llm/generate_reports.py——诊断脚本也要复用，跨层导入难看；② 独立新模块 src/analysis/realized_returns.py——单一函数不足立模块，过度设计；③ 回填逻辑并入 diagnose 脚本——诊断与写数据混在一个工具，违背单一职责，拒绝。

## R2. 收益口径与对齐

- **决策**：ret_N = (close[t+N] − close[t]) / close[t] × 100，t = event_date 在 K 线 dates 中的位置（当日收盘），N ∈ {3, 5} 个**交易日**；t+N 超出 K 线末尾 → None。前复权数据沿用项目现有口径（docs/data/kline 已前复权）。
- **理由**：与项目其他收益率计算一致（close.pct_change 族），交易日计数天然处理停牌/休市；None 处理对齐"不伪造"约定。
- **替代方案**：① 用 t+1..t+N 收益（不含当日）——spec 假设已定"含当日收盘为基准"口径，改则手算基准全变；② 自然日 5 天——节假日/停牌失真，拒绝；③ 用复权因子重算——数据不含复权因子列，拒绝。

## R3. 回填脚本设计（幂等 + 快照）

- **决策**：tools/backfill_market_feedback.py：① 读 market_feedback.json，若快照文件（market_feedback.backup_YYYYMMDD.json）不存在则先写快照；② 对每条样本按 code+event_date 定位 K 线计算 realized_ret_3d/5d，写入新字段并把 ret_3d_pct/ret_5d_pct 改为真实收益（原预测值存 forecast_ret_5d_pct）；③ 不可算样本 realized_*=null + flag；④ 原子写回 + 对比统计输出。幂等：快照只在首次创建；重跑覆盖式更新。
- **理由**：derived 数据再生成是合法操作（原始 K 线只读，FR-011）；快照保证可回滚审计；幂等要求来自 SC-005。
- **替代方案**：① 不保留快照直接覆盖——不可审计，拒绝；② 新建 v2 文件不动旧文件——消费方要迁移路径，复杂度高；③ 每日流水线增量回填——未来增强，本次一次性脚本即可。

## R4. 度量修复：directional_accuracy 定义与兼容

- **决策**：directional_accuracy = 方向一致数 / 决定性样本数；决定性样本 = |sentiment_score| >= 0.1 且 realized_ret_5d（或 3d 回退）非 None；方向一致 = sign(score) == sign(realized_ret)。旧 alignment_rate 字段原样保留（分母含全部样本、基于旧字段），并在 summary 增加 decisive_sample_count 与 no_score_sample_count 供审计。
- **理由**：中性样本（|score|<0.1）本就不表态，计入分母是度量缺陷（根因 2）；保留旧字段满足向后兼容（FR-006）。
- **替代方案**：① 直接改 alignment_rate 定义——破坏消费方（calibration.py）语义，拒绝；② 用 0.05 或 0.2 阈值——沿用 generate_soft_label 的 0.1 惯例，无理由另设；③ 加权准确率——过度复杂，先做简单正确的口径。

## R5. 置信区间与基线对比

- **决策**：Wilson score interval（95%）手写实现（纯 math，不引新依赖），与 50% 基线对比：区间下界 > 0.5 → 显著高于；上界 < 0.5 → 显著低于；否则无显著差异。样本 < 30 只给描述性结论并标注功效不足。
- **理由**：二项比例的标准做法；手写避免为一个小函数引入依赖；scipy 已在（statsmodels 依赖）但用不上其重型功能。
- **替代方案**：① 正态近似区间——小样本失真；② 精确 Clopper-Pearson——代码略长，Wilson 已足够；③ 仅点估计对比——不满足"含置信区间"的 spec 要求。

## R6. 测试策略

- **决策**：tests/test_market_feedback_realized.py（新）：① realized_return 手算对照（合成 close 序列）；② record_event 契约测试（预测值不得落入 ret 字段）；③ compute_summary directional_accuracy 构造样本手算；④ 回填幂等（tmp 数据两次运行逐字节一致）；⑤ 泄漏注入（用 event_date 之前 K 线 → 必须失败）；⑥ 诊断脚本在 tmp 夹具数据上运行输出报告。真实数据验证另行运行诊断脚本并归档报告。
- **理由**：AGENTS.md 要求离线夹具可复现 + 边界/缺失/失败路径；SC-004 要求 100% 覆盖。
- **替代方案**：只测工具不测契约——record_event 的契约是最核心修复点，必须测。

## R7. 诊断脚本结论约束

- **决策**：诊断报告分三段：根因审计（代码位置+样本证据）、分母构成分解、真实方向统计（含 Wilson CI 与基线对比）；结论只允许三种表述（正相关/无关/反转）且必须给出样本数与区间；报告写入 reports/sentiment_signal_diagnosis.md（覆盖式）。
- **理由**：SC-001/SC-003 要求结论以数据为准、不夸大；README 的教训就是"数字→结论"的推断链断了。
- **替代方案**：只输出表格不定结论——用户要的就是结论；报告写 JSON——md 更利于人读归档。

## 未决项

- 无。信号增强（词典/阈值/提示词）明确留 Phase 2；spec 0 澄清标记。