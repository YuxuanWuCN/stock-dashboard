# Task Breakdown: 2025Q2–2026Q7 存储市场物理隔离回测

- [x] **Task 1: 构建物理隔离原始数据集与 ground truth**
  - 在 `data/raw/backtest_storage_2025q2_2026q7/` 准备 2025-04-01 至 2026-07-31 的真实时序数据（行情、现货价、海关出口、多因子矩阵）。
  - 严格保持只读与时间截断。
- [x] **Task 2: 实现拟真交易人逐步推进回测执行器**
  - 研发 `src/analysis/storage_backtest_runner.py`。
  - 在 $t$ 日仅读取 $\le t$ 数据，计算 Fama-MacBeth 载荷、GFCA 坐标、NALE 图谱传导、Nowcasting 减值惩罚与 Trend Gate 状态。
  - 在 $t+1$ 日开盘撮合，精确计入买入 0.125% 与卖出 0.175% 摩擦成本及现金利息。
- [x] **Task 3: 运行回测并生成出版级高清图表与表格**
  - 生成 `reports/figures/backtest_storage_2025q2_2026q7/` 下的 3 张高清图表（净值对比图、水下回撤图、GFCA空间散点图，$\ge 200\text{ DPI}$）。
  - 生成 `reports/tables/backtest_storage_2025q2_2026q7/metrics_summary.md` 绩效统计对比表。
- [x] **Task 4: 同步输出数据至前端 HTML 大屏数据包**
  - 导出 `docs/data/paper/backtest_storage_2025q2_2026q7.json`，并在 `docs/index.html` 嵌入可视化回测卡片。
- [x] **Task 5: 单元测试与端到端 Smoke Test 验证**
  - 编写 `tests/test_storage_backtest_runner.py` 确保 100% 测试通过。
