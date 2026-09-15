# ⚠️ 作废说明：本目录报告基于历史合成数据，已全量作废

- **目录位置**：`reports/tables/backtest_paper_2024_2026_300stocks/`
- **涉及文件**：`accuracy_and_performance_report.md`
- **作废日期**：2026-09-10
- **状态**：**结论作废，原件保留为历史物证**

---

## 作废原因

1. 本目录报告所依据的原始价格输入 `data/raw/backtest_paper_2024_2026_300stocks/market_prices.csv` 经证实为 seed42 随机模拟生成（参见 `data/raw/backtest_paper_2024_2026_300stocks/DEPRECATED_DO_NOT_USE.md` 与 `PROJECT_SHARED_MEMORY.md` 第 226 行）。
2. 本目录中的检验值（如 `t=3.92, p<0.01`）来自历史原型脚本 `scripts/build_2024_2026_300stocks_backtest.py:704` 的硬编码字面量，非真实检验产物。
3. 本目录所有胜率、超额收益与检验结论一律作废，**严禁进入 2026 年中国国际大学生创新大赛（国创）网申、PPT、申报表及商业计划书**。
4. 最新真实评测结果请参阅 M4 产物目录：`reports/tables/pca_nale_integration/` 及对应 CLI `scripts/evaluate_pca_nale_integration.py`。
