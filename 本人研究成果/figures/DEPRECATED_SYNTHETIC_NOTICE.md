# ⚠️ 废弃警告：学术论文与研报图表 fig1~fig5 全量作废 (DEPRECATED SYNTHETIC ARTIFACT)

> **目录位置**：`本人研究成果/figures/`  
> **涉及核心图片**：`fig1` ~ `fig5` 系列 PNG 图像  
> **作废类型**：基于波形公式、高斯噪声与硬编码坐标伪造的学术图表  
> **详细总账索引**：详见项目主作废审计文件 `reports/DEPRECATED_SYNTHETIC.md`（§二.6）

---

## 1. 作废图片清单与技术造假证据

| 图表文件名 | 对应论文图注 / 宣称主题 | 造假代码位置与伪造机理 | 审计认定严重度 |
| :--- | :--- | :--- | :---: |
| `fig1_cumulative_equity_and_drawdown.png` | 策略累积净值与水下动态回撤对比图（MaxDD 11.75% vs 基准 >45%） | `scripts/generate_paper_figures.py:120-136`：基于合成存储数据，使用未经实证支撑的 11.75% 回撤曲线绘制 | **高** |
| `fig2_fama_macbeth_rolling_alpha.png` | 滚动 Fama-MacBeth 特质 Alpha 与特质信息比率时序图 | `src/analysis/gold_backtest_runner.py:464-465`<br>`src/analysis/green_backtest_runner.py:664-666`<br>`scripts/reproduce_paper_results.py:126-128`<br>使用正弦波加高斯噪声造假：`2.85 + 0.3*sin(...) + np.random.normal(0, 0.1, ...)` | **极高（伪造数据）** |
| `fig3_zigzag_trend_gate_biwin_defense.png` | 佰维存储 (688525) Trend Gate C 浪拦截与防御清仓图 | `scripts/generate_paper_figures.py:205-210`：硬编码拦截日期 `2026-05-15`，画图坐标与标注完全人工写死，非状态机动态产生 | **高** |
| `fig4_micron_hunting_ground_fibonacci.png` | 美光科技 (MU) 3 浪主升与 0.618 斐波那契支撑带买点图 | `scripts/generate_paper_figures.py:234-245`：实际读取的是 A 股佰维存储（688525），硬编码价格区间 `[143.8, 155.8]` 与买点坐标 `(2025-09-15, 148.5)` | **高** |
| `fig5_brier_score_calibration_curve.png` | 预测概率与 Brier Score 校准曲线图 | `scripts/generate_paper_figures.py:263-267`<br>`scripts/reproduce_paper_results.py:220-222`<br>使用固定种子构造虚假校准：`empirical_freqs = pred_probs + np.random.normal(0, 0.03)` | **极高（伪造数据）** |

---

## 2. 替代指引

- 上述 5 张图片严禁出现在任何学术论文（.tex / .pdf）、技术报告、PPT 汇报或申报书中；
- 所有正式科研插图必须由基于纯真实数据（CSMAR / 真实 K 线）的独立重跑脚本自动绘制，新图统一输出至：`reports/real_rebuild_20261010/figures/`。
