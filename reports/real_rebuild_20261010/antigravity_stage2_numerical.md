# P4/M4 数值被估量修正与真实数据重建阶段执行记录 (Stage 2 Numerical Estimands Log)

## 1. 执行命令与退出状态记录 (Execution Commands & Exit Statuses)

| 阶段 / 任务 | 执行命令 | 耗时 / 退出码 | 关键结果与产物状态 |
| :--- | :--- | :--- | :--- |
| **端到端全量数据重建** | `.venv\Scripts\python.exe scripts\run_real_m4_rebuild.py` | 228.5s / 退出码 0 | 全量事件研究 (166,485 事件)、1000 次 3 种设计安慰剂检验、584 截面 Fama-MacBeth HAC 回归与全部 Markdown 报告生成完毕 |
| **全量量化单元测试** | `.venv\Scripts\python.exe -m pytest tests\test_p4_real_quant.py -v` | 3.03s / 退出码 0 | **38 passed, 0 failed, 0 warnings**（含严格字节级报告一致性校验与全部新增手算断言） |
| **质量门禁小型套件** | `.venv\Scripts\python.exe tools\quality_gate.py small` | ~65s / 退出码 0 | 语法、配置、单元测试、FM 引擎、情绪度量全通过，生成报告 `.quality-state/reports/20261012092405-small-79bd9e.md` |
| **质量门禁状态核验** | `.venv\Scripts\python.exe tools\quality_gate.py status` | 退出码 0 | `small: 有效`，源码指纹一致 |

---

## 2. 产物清单与时间戳校验 (Rebuilt Artifacts Inventory)

目录：`reports/real_rebuild_20261010/`

| 产物文件名 | 文件大小 (Bytes) | 最新更新时间戳 | 检验状态 |
| :--- | :--- | :--- | :--- |
| `trend_gate_event_study.json` | 216,761 | 2026-10-12 09:22:15 | 包含 true maxdd、mae、exit_diagnostics、比率影响函数与稳健性 sensitivity |
| `trend_gate_placebo_1000.json` | 3,633,599 | 2026-10-12 09:22:15 | 完整 1000 次日期级/同日匹配/事件级安慰剂分布 |
| `fama_macbeth_hac_results.json` | 187,006 | 2026-10-12 09:22:36 | 修正无风险利率扣减口径、新增截距 alpha 统计、留痕稳健性 |
| `results.json` | 215,995 | 2026-10-12 09:22:36 | 完整复合实证结果数据载荷 |
| `report.md` | 20,819 | 2026-10-12 09:22:36 | 真实数据量化重建实证研究报告（严格现算现填） |
| `vs_old.md` | 6,603 | 2026-10-12 09:22:36 | 旧值 / v1 / v2 三方对账明细 |
| `paper_correction_checklist.md` | 5,377 | 2026-10-12 09:22:36 | 论文与申报材料删改清单（严格现算现填） |

---

## 3. 核心被估量与公式修正详情 (Formulas & Estimands Modifications)

### 3.1 真实峰谷最大回撤 vs 进场点最大不利偏离 (True Peak-to-Trough MaxDD vs MAE)
- **旧公式缺陷**：旧逻辑使用 $\min_t(p_t) / p_0 - 1$，混淆了“自进场点最大不利偏离 (MAE)”与“区间任意峰谷真实最大回撤 (Peak-to-Trough MaxDD)”。对价格序列 $[100, 120, 110]$，真实回撤为 $110/120 - 1 = -1/12 \approx -8.33\%$，而 MAE 为 $0.00\%$。
- **修正后公式**：
  $$\text{True MaxDD} = \min_{t \in [0, H]} \left(\frac{p_t}{\max_{0 \le s \le t} p_s} - 1\right)$$
  $$\text{MAE (Adverse Excursion)} = \frac{\min_{0 \le t \le H} p_t}{p_0} - 1$$
- **代码实现**：在 `scripts/p4_real_data_core.py` 中实现独立函数 `calc_peak_to_trough_drawdown`，返回字典 `{"maxdd": ..., "mae": ...}`。在 `build_trend_gate_events` 与 `summarize_events` 中分别计算 `maxdd_{h}d` 与 `mae_{h}d`，并在各级 JSON 中分别以 `mean_maxdd` 和 `mean_mae` 独立暴露，彻底杜绝概念混淆。

### 3.2 Fama-MacBeth 因子收益率与无风险利率平移口径 (Risk-Free Subtraction Invariance)
- **旧公式缺陷**：旧版本在计算各因子的 `annualized_premium_excess_244d` 时，错误地对所有因子斜率 $\lambda_f$ 统一扣除了年化无风险利率 $R_f$。但在截面 OLS 模型：
  $$R_{i, t+1} = \alpha_t + \sum_{f} \lambda_{f, t} z_{i, f, t} + \varepsilon_{i, t+1}$$
  由于因子 $z_{i, f, t}$ 已进行截面标准化（均值为 0，方差为 1），各因子斜率 $\lambda_{f, t}$ 对应零净投资、资金中性的多空组合超额收益，其本身已为超额收益，绝不包含无风险利率。若将因变量减去常数 $R_f$，仅引起截距项 $\alpha_t$ 的平移，各因子斜率 $\lambda_{f, t}$ 及其标准误、t 统计量严格保持不变。
- **修正后口径**：
  - 因子溢价 `annualized_premium_excess_244d` 设置为等于 `annualized_premium_244d`，并附详尽方法学注释 `rf_note` 保持 schema 兼容。
  - 在输出中新增截距项 $\alpha_t$ 的度量：`mean_alpha_daily`、`annualized_alpha_244d`、`annualized_alpha_excess_244d` 及 `alpha_newey_west_t`。

### 3.3 组间差异的比率影响函数推断与区块敏感性 (Paired Ratio Estimator & Influence Score)
- **旧公式缺陷**：事件级汇总均值实为比率估计量 $\hat{\mu} = \sum S_t / \sum N_t$。当各交易日事件数 $N_t$ 不等时，不能简单对未中心化的日度贡献做均值检验。同时，20 日重叠窗口存在长期自相关，单一 $q=5$ 或固定区块不足以完整捕获时序依赖。
- **修正后公式**：
  采用中心化影响函数分数（Centered Influence Score）：
  $$\psi_t = \frac{S_t - \hat{\mu}_X N_t}{\sum_\tau N_\tau} - \frac{R_t - \hat{\mu}_Y M_t}{\sum_\tau M_\tau}$$
  $$z_t = m \cdot \psi_t + \hat{\mu}_{\text{event}}$$
  其中 $m$ 为交易日数。对 $z_t$ 进行 Newey-West HAC 检验，以及对配对日度总和与频数 $(S_t, N_t, R_t, M_t)$ 进行成对移动区块 Bootstrap (`block_bootstrap_ratio_diff`)。
- **时序依赖与敏感性分析**：
  - 提供滞后阶数敏感性：自动阶数 $q_{\text{auto}}$、预声明窗口跨度 $q_{H-1}$（如 20 日窗口对应 $q=19$）及扩展阶数 $q_{\text{ext}} = \lfloor 1.5 \times q_{H-1} \rfloor$。
  - 提供区块长度敏感性：`block2`, `block5`, `block_h` ($H$), `block20`。
  - 显式记录配对交易日交集数量 `n_paired_days` 及交集比率。

### 3.4 安慰剂检验权重对齐与控制组截断披露 (Placebo Weighting & Truncation)
- **旧公式缺陷**：随机日期采样池按事件总和/总数进行池化均值计算，与按日等权的观测值存在权重失配；同日匹配在部分交易日池内合格样本不足时未披露截断信息。
- **修正后口径**：
  - 在 `run_date_placebo` 中同时计算池化分布与日等权分布 `dist_date_equal_ret_means`。
  - 在 `_placebo_p_values` 中：将日等权观测值与日等权安慰剂分布进行严格同权重对比（`date_equal_weighting_matched: True`）；将池化观测与池化安慰剂计算的经验 p 值显式标注为 `descriptive_mismatched_weights` 描述性指标，不再声称等权严格假设检验。
  - 在 `run_date_matched_placebo` 中：严格排除目标组标的，当池内样本不足 $k_t$ 时，不静默截断，而是记录 `control_insufficient`，并标记 `sample_equality_claimed: False`。
  - 增加退出日诊断 `exit_diagnostics`：统计跌停顺延次数 `n_exit_deferred` 与样本期末审查截断次数 `n_exit_censored`。

### 3.5 数据底座收益口径真伪与不可替代性披露 (Data-Return Provenance Disclosures)
- **事实与边界披露**：
  - CSMAR 主面板仅 99 支标的包含官方复权收益 `ret`，其余 200 支标的依赖收盘价收盘收益 `close_ret`。
  - 尽管两者中位差极小（$2.45 \times 10^{-7}$），但这绝不能在数学上证明未复权收盘收益等价于除权除息复权收益。
  - 未经复核的个股离群收益点不得声称全部已查证除权，保留其事实局限性。
  - 事件研究使用的收盘价收益基准与 Fama-MacBeth 回归所采用的可交易 $t+1$ 收益基准差异在研究报告与对账清单中进行了严格分立与披露。

---

## 4. 关键估计值与敏感性汇总 (Key Estimates & Sensitivity Results)

### 4.1 Trend Gate 事件研究核心度量（受约束口径，199 支标的）

| 组别 | 有效事件数 | 20日收益均值 | 胜率 | 真实峰谷最大回撤 | 进场点 MAE | 日均收益 NW t |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| **下行拦截组 (Trigger)** | 42,212 | **+2.68%** | 54.10% | **-8.66%** | **-5.46%** | 2.29 |
| **顺势组 (Uptrend)** | 44,897 | **+1.86%** | 49.63% | **-11.18%** | **-7.00%** | 1.60 |
| **纯对照组 (Neutral)** | 20,743 | **+0.94%** | 46.60% | **-9.71%** | **-6.37%** | 2.27 |
| **非触发池 (Not Downtrend Pool)** | 65,650 | **+1.57%** | 48.67% | **-10.70%** | **-6.80%** | 2.03 |

> **关键实证结论**：
> 下行拦截组 20 日真实平均最大回撤为 **-8.66%**（进场点最大不利偏离为 **-5.46%**），收益高于非触发池与纯对照组。但同日配对日等权差为 **-0.05%** ($NW\ t = -0.09, p = 0.9265$)，优势完全集中在普跌集中触发的少数交易日，不构成稳定的个股择时能力。

### 4.2 安慰剂检验权重敏感性与同日配对检验

| 安慰剂检验类型 | 观测值 | 安慰剂均值 ± 标准差 | 经验 p 值 (双侧) | 权重匹配状态与说明 |
| :--- | :--- | :--- | :--- | :--- |
| **随机日期 (池化口径)** | +2.68% | +1.57% ± 0.30% | $p = 0.0020$ | `descriptive_mismatched_weights` (描述性，权重不匹配) |
| **随机日期 (逐日等权)** | +1.46% | +1.52% ± 0.33% | **$p = 0.8851$** | `date_equal_weighting_matched: True` (**完全不显著**) |
| **同日匹配 (严格无放回)** | +2.68% | +0.95% ± 0.04% | $p = 0.0020$ | `date_matched_same_weight: True` (同日截面集中度效应) |

### 4.3 组间比率估计量配对差异及滞后/区块敏感性 (Trigger vs Pool, 20d)

- **事件加权配对差异**：$\Delta_{\text{weighted}} = +1.10\%$
- **中心化比率影响函数 HAC t 值**：
  - 自动阶数 ($q=5$): $t = +1.16, p = 0.2451$
  - 窗口跨度 ($q_{H-1}=19$): $t = +0.86, p = 0.3880$
  - 扩展阶数 ($q_{\text{ext}}=28$): $t = +0.83, p = 0.4072$
- **配对移动区块 Bootstrap 置信区间 (1000次)**：
  - IID 重抽样 (未考虑自相关): $t = +2.61, p = 0.0090$（严重低估标准误）
  - Block 2: $t = +1.73, p = 0.0841$
  - Block 5: $t = +1.26, p = 0.2088$
  - Block 20 ($H=20$): $t = +0.83, p = 0.4071$
- **配对交易日数**：$557$ 天（交集比率 99.82%）

### 4.4 Fama-MacBeth 因子截面回归（t+1 可交易收益）

| 因子 | 日均溢价 $\lambda$ | 年化溢价 (244d) | 超额年化溢价 | IID t | Newey-West t | FDR q 值 | 显著性判定 |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :--- |
| `mom_20d` | -0.00004 | -0.97% | -0.97% | -0.16 | **-0.16** | 0.8705 | 不显著 |
| `mom_60d` | -0.00006 | -1.57% | -1.57% | -0.25 | **-0.25** | 0.8705 | 不显著 |
| `vol_20d` | +0.00023 | +5.62% | +5.62% | +0.84 | **+0.79** | 0.6415 | 不显著 |
| `turnover_20d` | -0.00023 | -5.69% | -5.69% | -1.18 | **-1.17** | 0.5950 | 不显著 |
| `amihud` | +0.00040 | +9.85% | +9.85% | +3.53 | **+3.24** | 0.0073 | 显著 (但对涨停口径敏感) |
| `price_pos` | -0.00016 | -3.85% | -3.85% | -1.04 | **-1.04** | 0.5950 | 不显著 |

- **截距项 Alpha 统计**：
  - 日均 Alpha：$+0.000988$
  - 年化 Alpha：$+24.11\%$；扣除无风险利率超额 Alpha：$+22.61\%$
  - Newey-West t：$+1.61$ ($p = 0.1086$)

---

## 5. 新增独立单元测试覆盖 (Independent Unit Tests Added)

在 `tests/test_p4_real_quant.py` 中新增 4 个完全解耦的手算夹具与独立逻辑断言：
1. `test_drawdown_peak_to_trough_vs_adverse_excursion`:
   - 验证手算价格序列 `[100, 120, 110]` 严格返回 $\text{True MaxDD} = -1/12 \approx -0.08333$，而 $\text{MAE} = 0.0$。
   - 验证单调下跌序列 `[100, 90, 80]` 下两者数值严格相等。
2. `test_fama_macbeth_rf_subtraction_shifts_intercept_only`:
   - 构造随机截面收益与因子矩阵，分别进行原始收益回归与减去日度无风险利率 $R_f$ 的超额收益回归。
   - 严格断言因子的斜率估计向量 $\hat{\lambda}$、协方差矩阵与 t 统计量完全不变（差值 $< 10^{-14}$），而截距项 $\hat{\alpha}$ 精确减少 $R_f$。
3. `test_paired_ratio_influence_varying_counts_cancels_when_means_constant`:
   - 构造各交易日事件数剧烈变化（如 5 对 500）但每期真实截面均值处处相等的两组。
   - 严格断言中心化比率影响函数 $z_t$ 的离差全部为 0，比率差值为 0，HAC t 值严格等于 0，证明在频数剧烈变动下不会产生假阳性漂移。
4. `test_serial_correlated_ar1_understates_iid_se`:
   - 构造高自相关 AR(1) 过程 ($\rho = 0.8$)。
   - 严格断言 IID 标准误显著小于 Newey-West 标准误（至少低估 2 倍以上），验证时序依赖未被抹除。
5. **恢复严格字节级报告一致性断言**：
   - 移除了前序尝试中的字符串替换或宽松标准化，`test_generated_reports_match_artifacts` 对磁盘 Markdown 与生成函数输出执行严格 byte-exact 比对，完全通过。

---

## 6. 实证局限性声明 (Limitations & Provenance Disclosures)

1. **收益口径局限**：CSMAR 样本中仅 99 支股票包含官方复权收益 `ret`，200 支股票使用收盘价计算的近似收益。中位数差异极小并不证明未复权收盘价在除权除息日无失真。
2. **流动性与挂单可行性**：虽然模型施加了“进场日涨停不买、退出日跌停顺延”的纪律，但未考虑盘中流动性冲击成本、开盘跳空滑点及实际撮合队列延迟。
3. **样本时段局限**：样本区间为 2024-01-02 至 2026-08-28，包含特定市场环境与震荡下行期，普跌行情中的信号集中爆发主导了事件加权超额，无法外推至普涨牛市。
