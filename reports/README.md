# reports/ —— 实证产物与结果附录

本目录存放 Rainbow-FinGPT 的**可复现实证产物**：计量表格、学术图表、校准与回测输出。
正式的学术表述见 [`thesis/main.tex`](thesis/main.tex)（IEEE 期刊格式）；
项目总览与消融表见仓库根 [`README.md`](../README.md)。

> ⚠️ **先看这里**：[`作废声明/`](作废声明/) 与 [`DEPRECATED_SYNTHETIC.md`](DEPRECATED_SYNTHETIC.md)
> 记录了已被判定**不可用**的历史回测结果及其原因。引用本目录任何数字之前，请先确认它不在作废清单内。

## 论文与正式表述

| 路径 | 内容 |
|---|---|
| [`thesis/main.tex`](thesis/main.tex) | 期刊格式论文源文件 |
| [`storage_supercycle_paper.tex`](storage_supercycle_paper.tex) | 存储超级周期论文源文件（`../papers/` 亦有同名副本） |

## 计量表格与图表

| 路径 | 文件数 | 内容 |
|---|---:|---|
| [`tables/`](tables/) | 70 | 回归与回测计量表，含 `regression_768d/`、`pca_nale_integration/`、`ashare_pca_backtest/`、`backtest_paper_*` 等 |
| [`figures/`](figures/) | 105 | 论文用图（IC 森林图、Bootstrap 分布、净值曲线等），根 README 的 Figure Gallery 指向此处 |
| [`data/`](data/) | 1 | 结构化产物数据 |

## 运行时产物（由代码自动生成）

| 路径 | 文件数 | 生成方 |
|---|---:|---|
| [`calibration/`](calibration/) | 35 | 校准系统建议与验证报告 |
| [`sector_rotation/`](sector_rotation/) | 7 | `src/sector_rotation/monitoring.py` → `alerts_YYYYMMDD.json` |
| [`market_sentiment/`](market_sentiment/) | 27 | 每日市场情绪快照 |
| [`strategy_evolution/`](strategy_evolution/) | 16 | 周度策略演进分析 |
| [`prediction_accuracy/`](prediction_accuracy/) | 9 | 预测准确率记录 |

## 版本基准与重建证据

跨版本对比与实盘重建的证据链，用于验证"新版本相较前一版本是否有实质提升"。

| 路径 | 内容 |
|---|---|
| [`v2_vs_v3_comparison.md`](v2_vs_v3_comparison.md) | v2 / v3 对比 |
| [`static_vs_temporal_nale_comparison.md`](static_vs_temporal_nale_comparison.md) | 静态 vs 时序 NALE 对比 |
| [`bear_market_stress_refined_tnale_report.md`](bear_market_stress_refined_tnale_report.md) | 熊市压力测试 |
| [`real_rebuild_20261010/`](real_rebuild_20261010/) | 真实数据重建（19 文件） |
| [`fof_rebuild_20261013/`](fof_rebuild_20261013/) | FOF 重建与不变性审计 |
| [`fof_stress_20261014/`](fof_stress_20261014/) | FOF 压力测试（原始版） |
| [`fof_stress_20261014_fixed/`](fof_stress_20261014_fixed/) | FOF 压力测试（修正版，含独立复核） |

## 方法与假设

| 路径 | 内容 |
|---|---|
| [`assumptions.md`](assumptions.md) | 回测与建模假设登记（被 `src/assets/commodity/basis_term_structure.py` 等作为校准出处引用） |
| [`fama_macbeth_verification.md`](fama_macbeth_verification.md) | Fama-MacBeth 实现核对 |
| [`backtest_2024_2026_dual_simulation.md`](backtest_2024_2026_dual_simulation.md) | 300 标的两年双模拟 |
| [`sentiment_signal_diagnosis.md`](sentiment_signal_diagnosis.md) | 情绪信号诊断 |
| [`teacher_framework_validation.md`](teacher_framework_validation.md) | 导师框架验证 |
| [`方向校准修复验证报告.md`](方向校准修复验证报告.md) | 方向校准修复验证（另有同名 PDF） |
| [`波浪理论_文献综述.md`](波浪理论_文献综述.md) | 波浪理论文献综述 |
| [`绿电板块_增强版回测报告.md`](绿电板块_增强版回测报告.md) | 绿电板块回测（另有 `_最终版`） |

## 归档

| 路径 | 文件数 | 内容 |
|---|---:|---|
| [`个股深度复盘/`](个股深度复盘/) | 22 | 个股波浪与波动理论复盘（md 与 docx 双份），非引擎产物，仅作阅读材料 |
| [`历史归档/`](历史归档/) | 3 | 早期测试日志与文献阅读报告，无现役引用 |
| [`作废声明/`](作废声明/) | 2 | 回测结果与存储/黄金联合结论的作废告示 |

## 约束

- 本目录大部分内容被质量门禁的**存在性断言**依赖（`tests/test_c_cohort_provenance_invalidation.py`、
  `tests/test_e2e_production_acceptance.py` 等）。移动或删除任何条目之前，先全仓库检索其文件名。
- 依据根目录 `AGENTS.md`：未见实质提升不得覆盖旧版本产物，稳定基准必须保留。
