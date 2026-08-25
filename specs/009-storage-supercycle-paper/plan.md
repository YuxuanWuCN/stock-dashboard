# 实施规划 009：半导体存储超级周期学术论文与系统实现 (Plan-Kit 009)

## 1. 架构设计与论文组织 (Paper Organization)

论文题为：
**《Asset Pricing and Tactical Execution in the 2025–2026 Semiconductor Storage Supercycle: A Decoupled Triple-Engine Framework》**

### 章节设计：
- **Section 1: Introduction & Literature Review**
  - 存储周期特征（高资产刚性、剧烈价格弹性、扩产滞后性）。
  - LLM 在量化中的核心困境：幻觉漂移、时序不可靠、未来函数泄漏。
  - Decoupled Triple-Engine Framework 理论创新。
- **Section 2: Decoupled Triple-Engine Architecture**
  - 模块 1：SCNU-RAG 定性证据链、FOI 标注、10 题卡位矩阵与对抗性缩放。
  - 模块 2：Carhart 4 因子两阶段 Fama-MacBeth 资产定价与 Newey-West HAC 稳健估计。
  - 模块 3：因果 ZigZag 状态机、0.618 斐波那契支撑与 Trend Gate 布尔执行器。
- **Section 3: Mathematical Formalization & Theorems**
  - 形式化数学模型推导与状态转移证明。
- **Section 4: Empirical Backtest & Benchmark Calibration**
  - 2025–2026 历史数据回测（筑底、爆发、过剩三阶段）。
  - Table 2 标杆用例验证（BIWIN 最大回撤压制与 MU 夏普比率最大化）。
  - Brier Score 预测校准度与 Rank IC 检验。
- **Section 5: Discussion, Limitations & Future Roadmap**
  - 跨市场日历错位、ATR 自适应阈值、双轨因子库。
- **Section 6: Conclusion**

---

## 2. 图表与交付物清单 (Artifacts & Deliverables)

1. `reports/figures/fig0_triple_engine_framework.jpg`: 系统总体架构全景图。
2. `reports/figures/fig1_cumulative_equity_and_drawdown.png`: 组合累积净值与动态回撤图。
3. `reports/figures/fig2_fama_macbeth_rolling_alpha.png`: Fama-MacBeth 滚动 Alpha 与 IR 时序图。
4. `reports/figures/fig3_zigzag_trend_gate_biwin_defense.png`: 佰维存储 (688525) C 浪拦截实证图。
5. `reports/figures/fig4_micron_hunting_ground_fibonacci.png`: 美光 (MU) 0.618 斐波那契买点实证图。
6. `reports/figures/fig5_brier_score_calibration_curve.png`: 预测概率与 Brier Score 校准图。
7. `paper/storage_supercycle_paper.tex`: 完整 LaTeX 论文代码。
8. `STORAGE_SUPERCYCLE_README.md`: 总结文档。
