# ⚠️ 废弃警告：本目录全部数据已于 2026-09-10 全量作废（禁止用于任何回测或实证）

- **目录位置**：`data/raw/backtest_paper_2024_2026_300stocks/`
- **包含文件**：`market_prices.csv`、`universe_metadata.csv`、`factors.csv`、`market_temperature.csv`
- **作废日期**：2026-09-10（经项目接续独立审计核实）
- **审计记录**：
  - `PROJECT_SHARED_MEMORY.md`（第 226 行）
  - `reports/tables/nale_alpha_week1/recovery-audit-20260910/data_audit.md`
  - `docs/handoff_pca_to_nale_integration.md`（§9-6、F11）

---

## 1. 作废原因与事实核定

本目录下的行情文件 `market_prices.csv` 经源码反查与内存重算证实为**早期通过 `scripts/build_2024_2026_300stocks_backtest.py`（seed=42）随机模拟生成的工程占位假数据**：
1. **生成逻辑**：`scripts/build_2024_2026_300stocks_backtest.py:409-444` 使用 `np.random.normal` 生成大盘及 300 支个股价格，日历仅为工作日简单过滤，未处理法定节假日与真实停牌。
2. **价格严重失真**：
   - 宁德时代（300750）2024-01-02 模拟价格为 309.78 元，真实价格为 156.83 元，且随时间偏差高达数倍；
   - 比亚迪（002594）最大偏差超过 2000%；
   - `000300.SH` 列非真实沪深 300 指数，比值在 0.81~1.30 之间漂移。
3. **衍生报告作废**：
   - 早期依据该文件生成的《双轨实战对决报告》（`reports/backtest_2024_2026_dual_simulation.md`，宣称 +157%~+169% 累计收益）**完全不具备真实市场有效性**，严禁进入国创网申申报书、PPT 与答辩汇报。

---

## 2. 为什么保留原文件？

遵循量化科研与审计规范（不销毁历史物证），本目录原文件仅作为**溯源审计证据与反向防护测试夹具**保留，受自动化门禁（如 `tests/test_student_b_factor_panel.py`）监控，防止任何生产代码误读。

---

## 3. 正式真实数据指引（全员必须统一使用）

所有 300 支 A 股实证研究、因子计算与策略回测，必须严格使用以下经三重审计的真实数据：

| 模块 | 正式数据/脚本路径 | 描述 |
| :--- | :--- | :--- |
| **真实行情大表** | `data/task_split/csmar_master/csmar_factor_panel_master.csv` | 299 支 × 644 个真实交易日（2024-01-02 至 2026-08-28）真实行情与技术指标 |
| **统一收益口径** | `src/data/return_basis.py` | 严格区分 A 组分红再投资总收益 `Dretwd` 与 B/C 组前复权口径 |
| **点在时间面板** | `src/data/pca_nale_asof_panel.py` | 具备无前视因果时间戳的 As-Of S0 因子面板工厂 |
| **走步评测引擎** | `scripts/evaluate_pca_nale_integration.py` | M4 级无未来函数走步集成回测 CLI |
