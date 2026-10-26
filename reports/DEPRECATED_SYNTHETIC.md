# Rainbow_FinGPTv2 历史被污染产物与合成数据全量作废清单 (Master Deprecation Ledger)

> **发布日期**：2026-10-10  
> **依据规范**：项目学术诚信与真实数据重建方案（§P2、§7）及 A1/A2/A3 独立深度审计证据链  
> **核心原则**：  
> 1. **物理保留，全面封存**：依据科研溯源规范，严禁物理删除或覆盖任何历史文件，全部历史文件作为防伪审计物证与反向测试夹具保留；  
> 2. **显式作废，坚决阻断**：所有下述产物打上废弃标注（DEPRECATED），禁止作为学术论文、申报书、商业计划书或正式投资决议的实证依据；代码层面坚决阻断生产链路读取；  
> 3. **统一指引，纯真替代**：所有正式研究与量化回测一律重定向至基于 CSMAR 主面板等纯真实数据源构建的全新产物目录 `reports/real_rebuild_20261010/`。

---

## 一、 判别准则与三指纹检验标准

为科学甄别真实市场行情与合成数据，审计体系确立了**三大统计指纹**检验准则（同一算法，计算日收益率序列 $r_t$）：

1. **超额峰度指纹（Excess Kurtosis）**：真实 A 股日收益具有显著肥尾特征，超额峰度 $\text{Kurt}(r) - 3 > 2.0$（典型真实范围 $+2 \sim +14$）；而独立同分布正态伪随机数（PRNG）的超额峰度接近 0。
2. **波动率聚集指纹（Volatility Clustering）**：真实市场存在明显的波动聚集效应，$|r_t|$ 的一阶自相关系数 $\text{Corr}(|r_t|, |r_{t-1}|) \approx [0.10, 0.35]$；PRNG 序列的绝对收益自相关接近 0。
3. **交易日历合法性指纹（Calendar Validity）**：真实 A 股行情严格遵循法定节假日休市规定；合成数据多由工作日反推或等间隔步长生成，包含元旦、春节、清明、劳动节、端午、国庆等法定休市日。

| 数据集 / 产物目录 | 样本形状 | 时间跨度 | 法定休市日天数 | 平均超额峰度 | $\|r\|$ 一阶自相关 | 指纹判真结论 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **真实基准**：`data/task_split/csmar_master/csmar_factor_panel_master.csv` | 192,199×22 (299 标的) | 2024-01-02 ~ 2026-08-28 | 0 天 | **+4.205** | **+0.2155** | **真实市场数据** |
| `data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv` | 694×301 | 2024-01-02 ~ 2026-08-28 | 23 天 | +0.066 | +0.0240 | **伪造合成数据** |
| `data/raw/backtest_paper_100d_202stocks/market_prices.csv` | 99×203 | 2026-04-07 ~ 2026-08-21 | 4 天 | +0.445 | +0.0202 | **伪造合成数据** |
| `data/raw/backtest_paper_60d_202stocks/market_prices.csv` | 60×203 | 2026-06-01 ~ 2026-08-21 | 1 天 | +0.346 | -0.0254 | **伪造合成数据** |
| `data/raw/backtest_storage_2025q2_2026q7/market_prices.csv` | 349×17 | 2025-04-01 ~ 2026-07-31 | 14 天 | +0.025 | +0.0036 | **伪造合成数据** |

---

## 二、 受污染产物逐项清单与废弃原因

### 1. 300 支股票合成行情与衍生回归产物 (`data/raw/backtest_paper_2024_2026_300stocks/`)

- **涉及文件路径**：
  - 数据文件：`Rainbow_FinGPTv2/data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv`
  - 数据文件：`Rainbow_FinGPTv2/data/raw/backtest_paper_2024_2026_300stocks/factors.csv`
  - 数据文件：`Rainbow_FinGPTv2/data/raw/backtest_paper_2024_2026_300stocks/universe_metadata.csv`
  - 数据文件：`Rainbow_FinGPTv2/data/raw/backtest_paper_2024_2026_300stocks/market_temperature.csv`
  - 衍生报告：`Rainbow_FinGPTv2/reports/tables/regression_300stocks/`（全量表格与报告）
  - 衍生报告：`Rainbow_FinGPTv2/reports/tables/regression_768d/`（全量表格与报告）
  - 衍生报告：`Rainbow_FinGPTv2/reports/backtest_2024_2026_dual_simulation.md`
- **污染机理与事实**：
  1. **代码级随机数生成**：由 `scripts/build_2024_2026_300stocks_backtest.py:362, 391-460` 使用固定伪随机种子 `np.random.seed(42)`，通过 `daily_ret = np.random.normal(...)` 及基准价格 `np.random.uniform(...)` 生成 300 支股票价格与指数序列。
  2. **价格脱离现实**：宁德时代（300750）首日价格为 309.78 元（真实价格 156.83 元）；平安银行（000001）首日价格为 83.42 元（真实价格 9.35 元，偏差高达 +792%）；生成的 `000300.SH` 列与真实 510300 ETF 日收益相关系数仅为 0.1081。
  3. **内建假 Alpha 循环自证**：在生成行情时，各标的直接按 `universe_metadata.csv` 中预置的 `(beta, alpha)` 注入超额收益，所谓"筛选出 75 支 True Alpha"实为生成器硬编码注入的必然产物。
  4. **下游报告越权读取**：尽管该数据集在 2026-09-10/16 曾被标注作废（`DEPRECATED_DO_NOT_USE.md`），但 `scripts/run_300stocks_deep_regression.py:46` 与 `scripts/run_768d_high_dimensional_regression.py:171` 在 2026-09-29 仍越权读取此目录，产出全部 Fama-MacBeth 回归报告。
- **替代指引**：
  - 必须完全停用该目录下所有 CSV；
  - 截面定价与多因子分析统一使用真实 CSMAR 主面板 `data/task_split/csmar_master/csmar_factor_panel_master.csv`；
  - 真实数据 Fama-MacBeth 重新估计结果见 `reports/real_rebuild_20261010/fama_macbeth_report.md`。

---

### 2. 100 日 202 支股票物理隔离回测报告与数据 (`reports/tables/backtest_paper_100d_202stocks/`)

- **涉及文件路径**：
  - 报告文件：`Rainbow_FinGPTv2/reports/tables/backtest_paper_100d_202stocks/accuracy_and_performance_report.md`
  - 原始数据：`Rainbow_FinGPTv2/data/raw/backtest_paper_100d_202stocks/market_prices.csv`
  - 产物数据：`Rainbow_FinGPTv2/docs/data/paper/backtest_100d_202stocks.json`
- **污染机理与事实**：
  1. **反向随机游走造假**：生成器 `scripts/build_100d_202stocks_backtest.py:42, 59-101` 使用 `np.random.seed(42)`，对前 39 天行情执行反向随机游走 `daily_ret = np.random.normal(0.0002, 0.015, size=len(cols))`，因子与大盘温度全为正态白噪声。
  2. **样本天数造假**：实际为 99 个交易日（含 4 个法定节假日，真实有效工作日仅 95 天），报告宣称"100 个交易日、19796 个独立样本点"。
  3. **指标硬编码**：
     - Harvey t-stat 在代码第 308 行硬编码为 `3.85`，第 344 行模板写死 `**t = 3.85 (p < 0.01)**`；
     - 基准 MaxDD 与 Sharpe 在代码第 356-357 行硬编码（等权基准写死 8.50%/0.85，沪深 300 写死 5.20%/0.65）。在底层 CSV 上实际复算真实 MaxDD 分别为 10.86% 与 11.33%，真实 Sharpe 分别为 -1.35 与 -1.29（基准实际深度亏损，报告篡改为正夏普）；
     - 20 日命中率在第 304 行直接由 `hit_5d * 0.98` 公式化伪造；
     - 胜率 30.48%、盈亏比 0.94，单笔期望 $E = 0.3048 \times 0.94 - (1-0.3048) = -0.4087$（显著负期望），正文文字却颠倒黑白写为"实现正向数学期望"。
- **替代指引**：
  - 撤回全池 100 日"年化 218.6%、夏普 18.35"等不可信宣称；
  - 正式事件研究必须在经三指纹检验的真实标的池上重跑，参见 `reports/real_rebuild_20261010/trend_gate_event_study.json`。

---

### 3. 存储超级周期 2025Q2–2026Q7 回测报告与数据 (`reports/tables/backtest_storage_2025q2_2026q7/`)

- **涉及文件路径**：
  - 报告文件：`Rainbow_FinGPTv2/reports/tables/backtest_storage_2025q2_2026q7/metrics_summary.md`
  - 数据文件：`Rainbow_FinGPTv2/data/raw/backtest_storage_2025q2_2026q7/market_prices.csv`
  - 产物数据：`Rainbow_FinGPTv2/docs/data/quantitative/backtest_storage_2025q2_2026q7.json`
- **污染机理与事实**：
  1. **合成日历与静默伪造**：底层价格数据包含 349 天，含有 14 个以上 A 股法定休市日；超额峰度仅 +0.025，无波动聚集性。回测运行器 `src/analysis/storage_backtest_runner.py:112-132` 在缺少标的时通过 `np.random.seed(42)` + `np.random.normal(0.0005, 0.015, T)` 静默合成价格。
  2. **Brier 兜底造假**：`src/strategies/storage_supercycle_backtest.py:541-542` 在无有效预测对时直接返回硬编码常量 `brier_score = 0.185`，从未在真实样本对上计算过。
  3. **Alpha 门控兜底注入**：`storage_supercycle_backtest.py:358-362` 数据不足时人为注入 `alpha_val=0.0015, ir_val=0.45*sqrt(252)` 强行放行；实际判定条件被放宽为 `p < 0.20 or alpha > 0`，推翻了 `p < 0.05 且 IR >= 0.30` 的铁律门禁。
  4. **t 统计量性质偷换**：所谓 `Harvey t = 3.665 (p < 0.01)` 实为单一策略超额收益均值的普通 t 检验，既未做 Harvey-Liu-Zhu 多重检验校正，亦未修正重叠窗口的强自相关性，且写死 `p < 0.01`。
- **替代指引**：
  - 若存储标的无完整高密真实面板支持，该专题在正式学术论证中予以剔除或降级为局限案例；
  - 纯真替代结果参见 `reports/real_rebuild_20261010/`。

---

### 4. 存储 + 黄金跨周期联合回测报告 (`reports/tables/backtest_storage_gold_joint_report.md`)

- **涉及文件路径**：
  - 报告文件：`Rainbow_FinGPTv2/reports/tables/backtest_storage_gold_joint_report.md`
  - 产物数据：`Rainbow_FinGPTv2/docs/data/quantitative/backtest_storage_gold_joint.json`
  - 产物数据：`Rainbow_FinGPTv2/docs/data/paper/backtest_storage_gold_joint.json`
- **污染机理与事实**：
  1. **数据源污染**：`src/analysis/storage_gold_joint_runner.py:84-114` 优先读取已作废的 300stocks 随机数据，若不存在则现场用 seed=42 生成 14 支虚假标的。
  2. **结论与自身数据完全矛盾**：
     - 回撤恶化被写为压制：正文声称"将最大回撤由 11.48% 强力压制至 12.50%"，实际 12.50% 比 11.48% 恶化了 +1.02 个百分点；
     - 强相关被写为正交：相关系数 $\rho = 0.7413$，属于高度正相关，正文却妄言"呈现显著的近乎正交弱相关性"；
     - 波动降幅夸大：实际波动降幅为 19.35%，正文虚标为"降低了超 30%"；
     - 检验量硬编码：`storage_gold_joint_runner.py:266` 硬编码 `harvey_alpha_t_stat = 3.82`。
- **替代指引**：
  - 跨资产大类配置分析采用真实的期货连续主力合约（AU、SA、FG）与真实 A 股行情重算；
  - 严谨资产相关性与组合分散化指标见 `reports/real_rebuild_20261010/`。

---

### 5. 增强型回测空壳结果文件 (`reports/backtest_results_enhanced.json`)

- **涉及文件路径**：
  - 数据文件：`Rainbow_FinGPTv2/reports/backtest_results_enhanced.json`
- **污染机理与事实**：
  1. **底层序列全空**：`nav_series`（`dates`, `strategy`, `csi300`, `green_etf`, `green_ew`）、`regime_history`、`position_history` 全部为空数组 `[]`，没有任何底层交易或净值序列，完全无法独立复现。
  2. **数学逻辑严重自相矛盾**：
     - `total_return = 0.302` 与 `annualized_return = 0.302` 逐字相同（未做年化运算）；而记录的市场状态天数合计为 $95 + 68 + 75 = 238$ 天（非 252 天）；
     - 预测覆盖率与阈值关系非单调（0.50 对应 0.85，0.60 对应 0.45，0.70 对应 0.689，0.80 对应 0.15）；
     - 最大仓位 `max_position = 1.44`（144%），违反了项目"现金非负、无融券杠杆"的基础假设。
- **替代指引**：
  - 本文件作为纯粹空壳占位文件，全盘废弃；
  - 绿电与大盘真实走步回测结果见 `reports/real_rebuild_20261010/`。

---

### 6. 论文与答辩插图 Fig 1 ~ Fig 5 (`本人研究成果/figures/`)

- **涉及文件路径**：
  - `Rainbow_FinGPTv2/本人研究成果/figures/fig1_cumulative_equity_and_drawdown.png`
  - `Rainbow_FinGPTv2/本人研究成果/figures/fig2_fama_macbeth_rolling_alpha.png`
  - `Rainbow_FinGPTv2/本人研究成果/figures/fig3_zigzag_trend_gate_biwin_defense.png`
  - `Rainbow_FinGPTv2/本人研究成果/figures/fig4_micron_hunting_ground_fibonacci.png`
  - `Rainbow_FinGPTv2/本人研究成果/figures/fig5_brier_score_calibration_curve.png`
- **污染机理与事实**：
  1. **Fig 1（累积净值与水下回撤）**：基于上述虚假存储合成行情与不实指标（回撤压制至 11.75% vs 基准 >45%）；
  2. **Fig 2（滚动特质 Alpha 与 IR）**：图形生成器在 `gold_backtest_runner.py:464-465`、`green_backtest_runner.py:664-666` 及 `reproduce_paper_results.py:126-128` 中直接使用正弦波加高斯白噪声伪造 t 统计量（如 `2.85 + 0.3*sin(...) + noise`）；
  3. **Fig 3（佰维存储 Trend Gate 防御图）**：在 `generate_paper_figures.py:205-210` 中写死拦截日期 `2026-05-15` 与画图坐标；
  4. **Fig 4（美光 MU 斐波那契猎场入场图）**：把 A 股佰维存储（688525）数据错标为美光 MU（USD 计价），并在 `generate_paper_figures.py:234-245` 中硬编码 Fibonacci 支撑带区间 `[143.8, 155.8]` 及买入入场点 `(2025-09-15, 148.5)`；
  5. **Fig 5（Brier Score 校准曲线）**：在 `generate_paper_figures.py:263-267` 与 `reproduce_paper_results.py:220-222` 中直接使用 `np.random.seed(42)` 和 `empirical_freqs = pred_probs + np.random.normal(0, 0.03)` 伪造校准曲线。
- **替代指引**：
  - 严禁在后续论文终稿与 PPT 中使用这 5 张图；
  - 重新生成的图表必须从真实回测落盘的逐日明细中矢量化绘制，并保存于 `reports/real_rebuild_20261010/figures/`。

---

### 7. 11 份个股波浪理论复盘中的模板化复制粘贴段落 (`reports/`)

- **涉及文件路径（共 11 份）**：
  1. `Rainbow_FinGPTv2/reports/山东黄金_波浪与波动理论深度复盘.md`
  2. `Rainbow_FinGPTv2/reports/立新能源_波浪与波动理论深度复盘.md`
  3. `Rainbow_FinGPTv2/reports/股票 000021_波浪与波动理论深度复盘.md`
  4. `Rainbow_FinGPTv2/reports/股票 001309_波浪与波动理论深度复盘.md`
  5. `Rainbow_FinGPTv2/reports/股票 002155_波浪与波动理论深度复盘.md`
  6. `Rainbow_FinGPTv2/reports/股票 300308_波浪与波动理论深度复盘.md`
  7. `Rainbow_FinGPTv2/reports/股票 301308_波浪与波动理论深度复盘.md`
  8. `Rainbow_FinGPTv2/reports/股票 600489_波浪与波动理论深度复盘.md`
  9. `Rainbow_FinGPTv2/reports/股票 601899_波浪与波动理论深度复盘.md`
  10. `Rainbow_FinGPTv2/reports/股票 603986_波浪与波动理论深度复盘.md`
  11. `Rainbow_FinGPTv2/reports/股票 688525_波浪与波动理论深度复盘.md`
- **污染机理与事实**：
  上述 11 份不同行业、不同标的的个股复盘报告中，其第一节"核心结论与老师理论观点的数据对照"（第 12-18 行），全部逐字完全复制了立新能源（001258）的特定波段数据：
  ```markdown
  | **1. 短期翻倍与高位风险** | 滚动60日低点涨幅 / 距峰值回撤 | 2026-07-24达 **+100.8%**，峰值 **+135.3%** | ✅ **完全证实**。翻倍后波动率(ATR)从3.2%飙升至9.5% |
  | **2. 翻倍及时止盈/减仓** | 翻倍日(07-24)清仓 vs 持有最大回撤 | 清仓完全避开后续 **-18.98%** 连续两日跌停 | ✅ **完全证实**。显著降低尾部下行风险 |
  | **3. 回调是早晚的事** | 极值波段回调率 (Fibonacci回撤) | 6波主升行情中 **5波在4~7天内回调 ≥10%** | ✅ **完全证实**。主升浪后回调概率 **83.3%** |
  ```
  在佰维存储（688525）、中际旭创（300308）、紫金矿业（601899）等完全不相关的股票上，均出现"2026-07-24 翻倍达 +100.8%"、"躲过 -18.98% 连续两日跌停"以及"回调概率 83.3%"。这属于典型的模板化批量复制粘贴，构成虚假证据链。
- **替代指引**：
  - 该 11 份报告的第一节数据对照表格全部作废；
  - 各标的的真实波动特征由统一事件研究脚本独立计算，参见 `reports/real_rebuild_20261010/`。

---

### 8. 伪造与硬编码统计指标汇编 (Fabricated Metrics Ledger)

| 伪造 / 篡改指标 | 代码中所在位置 | 表现形式与造假手段 | 真实情况与规范处理 |
| :--- | :--- | :--- | :--- |
| **Brier 分数 0.185** | `src/strategies/storage_supercycle_backtest.py:541-542` | `else: brier_score = 0.185 # 标准基线校准值`，作为兜底常量 | 真实样本对长度为 0，从未算出过真实值。应返回 `None` 并标记 `no_predictions`；学术界废除"BS ≤ 0.25 为优秀"的荒谬门槛，改报 Brier Skill Score。 |
| **Harvey t 统计量 3.92 / 3.85 / 3.82** | `scripts/build_2024_2026_300stocks_backtest.py:685`<br>`scripts/build_100d_202stocks_backtest.py:308`<br>`src/pipeline/paper_60d_evolution_runner.py:394`<br>`src/analysis/storage_gold_joint_runner.py:266` | 写死数值字面量，并附带硬编码 `p < 0.01` 字符串直接输出至 Markdown 报告 | 并非来自回归估计或协方差矩阵。必须通过真实 Newey-West HAC 滚动回归计算真实 t 值并披露多重检验次数。 |
| **派生 20 日预测命中率** | `scripts/build_100d_202stocks_backtest.py:304`<br>`scripts/build_2024_2026_300stocks_backtest.py:681`<br>`src/pipeline/paper_60d_evolution_runner.py:361` | `directional_hit_rate_20d: hit_5d * 0.98`<br>`directional_hit_rate_20d: hit_5d * 0.96`<br>`hit_20d = sign(score) == sign(actual_5d * 1.5)` | 拿 5 日命中率或收益直接乘以比例系数伪造 20 日表现。必须使用严格对齐的未来 20 日真实实现收益进行无偏统计。 |
| **伪装 HAC 的 IID 标准误** | `scripts/run_300stocks_deep_regression.py:260-264` | `fm_se = std_daily / np.sqrt(T)`，纯横截面 IID 公式，报告正文标注为"自适应 Newey-West HAC" | 未进行序列相关调整，低估标准误、虚高显著性。必须使用真实 Bartlett 核函数计算长期方差并严格采用理论自适应滞后阶数。 |
| **不存在的 1000 次安慰剂置换检验** | `本人研究成果/README.md:49`<br>论文正文与申报书多处 | 声称"1000 次安慰剂置换检验 p < 0.001 证明因果经济学逻辑" | 仓内仅有 `supply_chain_graph.py` 的 100 次拓扑洗牌（且其注释明确声明不代表预测能力）。纯属未曾落盘执行的虚构实验。P4 已实施真实 1000 次随机日期抽样检验并落盘。 |
| **下行/上行捕获比 (DR/UR/非对称比)** | `本人研究成果/README.md:49`<br>`Asymmetric_Downside_Risk_Defense_Paper.tex:76, 378` | 宣称"DR=0.28, UR=0.82, 非对称捕获比 2.93" | 全仓 `src/` 搜索无任何 capture ratio 计算逻辑或产出文件。属于无源凭空捏造。 |
| **夸大收益 +490.79% / +159.01% / 夏普 4.627** | 研报 PDF、商业计划书、网申申报书 | 宣称"全周期 +490.79%、夏普 4.627、+159.01% 累计收益" | 溯源查明为误将某一交易日的中间净值点（如 2025-09-11 净值 1.5901）或单点指标误当作期末累计指标，仓内无任何全周期 Sharpe=4.627 的数据。 |

---

## 三、 替代方案与数据指引 (Clean Replacement Guide)

所有团队成员、自动化代理与研究人员，即日起必须遵循以下重定向路径：

| 模块 / 任务类型 | 已作废路径（严禁使用） | 正式纯真实替代路径 | 数据说明与口径 |
| :--- | :--- | :--- | :--- |
| **A 股全市场真实因子与行情** | `data/raw/backtest_paper_2024_2026_300stocks/` | `data/task_split/csmar_master/csmar_factor_panel_master.csv` | 299 标的 × 644 交易日，三指纹检验通过，超额峰度 +4.205 |
| **K 线行情数据清单** | 任意无来源 JSON | `reports/real_rebuild_20261010/data_inventory.csv` | 181 支 K 线经日历、缺口、假日三指纹核定，MU 明确排除 |
| **Trend Gate 事件研究与安慰剂** | `reports/tables/backtest_paper_100d_202stocks/` | `reports/real_rebuild_20261010/trend_gate_event_study.json` | 逐日推进无前视，考虑跌停不可成交限制，真实 1000 次安慰剂落盘 |
| **Fama-MacBeth 滚动回归** | `reports/tables/regression_300stocks/` | `reports/real_rebuild_20261010/fama_macbeth_hac_results.json` | 真实自适应滞后 $q=\lfloor 4(T/100)^{2/9} \rfloor$，报告 BH-FDR 与 Bonferroni |
| **真实对比与差异归因审计** | 历史模板化报告 | `reports/real_rebuild_20261010/vs_old.md` | 新旧指标逐项诚实对比，坦诚披露未达显著性之真实结论 |

---

## 四、 本清单在代码库各受污染目录的部署映射

为确保开发者在浏览具体受污染目录时能第一时间获知作废状态，本清单同步在以下目录部署轻量化通知标记文件：

1. `Rainbow_FinGPTv2/data/raw/backtest_paper_2024_2026_300stocks/DEPRECATED_SYNTHETIC_NOTICE.md`
2. `Rainbow_FinGPTv2/reports/tables/backtest_paper_100d_202stocks/DEPRECATED_SYNTHETIC_NOTICE.md`
3. `Rainbow_FinGPTv2/reports/tables/backtest_storage_2025q2_2026q7/DEPRECATED_SYNTHETIC_NOTICE.md`
4. `Rainbow_FinGPTv2/本人研究成果/figures/DEPRECATED_SYNTHETIC_NOTICE.md`
5. `Rainbow_FinGPTv2/reports/作废声明/DEPRECATED_STORAGE_GOLD_JOINT_NOTICE.md`
6. `Rainbow_FinGPTv2/reports/作废声明/DEPRECATED_BACKTEST_RESULTS_ENHANCED_NOTICE.md`
